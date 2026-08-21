"""Acesso ao banco operacional. Opcional por configuração (ADR-0018).

Sem `DATABASE_URL` todas as funções viram no-op e a API responde inferência
normalmente. Degradar em vez de falhar é deliberado: exigir banco para responder uma
inferência tornaria a avaliação mais frágil sem tornar o modelo melhor.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from typing import Any, Iterator

from src.utils import get_logger

logger = get_logger("db")

_POOL: Any = None


def enabled() -> bool:
    return bool(os.environ.get("DATABASE_URL"))


def init() -> bool:
    """Abre o pool e aplica o schema, se houver banco configurado."""
    global _POOL
    if not enabled():
        logger.info("Sem DATABASE_URL: persistência desativada.")
        return False
    try:
        from psycopg_pool import ConnectionPool
    except ImportError:
        from psycopg import connect  # fallback sem pool

        _POOL = connect(os.environ["DATABASE_URL"])
        logger.info("Conexão direta com o banco estabelecida.")
        return True

    _POOL = ConnectionPool(os.environ["DATABASE_URL"], min_size=1, max_size=4, open=True)
    logger.info("Pool de conexões aberto.")
    return True


@contextmanager
def cursor() -> Iterator[Any]:
    if _POOL is None:
        raise RuntimeError("Banco não inicializado.")
    if hasattr(_POOL, "connection"):
        with _POOL.connection() as conn, conn.cursor() as cur:
            yield cur
    else:
        with _POOL.cursor() as cur:
            yield cur
            _POOL.commit()


def register_model(metadata: dict) -> None:
    """Registra a versão em operação. Idempotente: reexecutar não duplica."""
    if not enabled():
        return
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO model_versions
                (version, git_sha, data_sha256, metrics, thresholds, trained_at,
                 promoted_at, status)
            VALUES (%s, %s, %s, %s, %s, %s, now(), 'production')
            ON CONFLICT (version) DO UPDATE
                SET status = 'production', promoted_at = now()
            """,
            (
                metadata["version"], metadata["git_sha"], metadata["data"]["sha256"],
                json.dumps(metadata["metrics"]), json.dumps(metadata["policy"]),
                metadata["created_at"],
            ),
        )
    logger.info("Versão %s registrada como production.", metadata["version"])


def record_decision(
    features: dict, amount: float, occurred_at_seconds: float,
    version: str, score: float, band: str, thresholds: dict, explanation: dict | None,
) -> int | None:
    """Grava transação e decisão; enfileira para revisão quando for o caso.

    Os limiares vigentes são gravados **junto com a decisão**: sem isso, uma decisão
    passada deixa de ser auditável assim que a política mudar.
    """
    if not enabled():
        return None
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO transactions (occurred_at, amount, features)
            VALUES (to_timestamp(%s), %s, %s) RETURNING id
            """,
            (occurred_at_seconds, amount, json.dumps(features)),
        )
        transacao_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO decisions
                (transaction_id, model_version, score, band, t_low, t_high, explanation)
            VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (transacao_id, version, score, band,
             thresholds["t_low"], thresholds["t_high"],
             json.dumps(explanation) if explanation else None),
        )
        decisao_id = cur.fetchone()[0]

        # A faixa do meio é o único ponto do sistema que gera rótulo em horas em vez
        # de semanas — é a fonte de observabilidade mais rápida (ADR-0014).
        if band == "manual_review":
            cur.execute(
                "INSERT INTO review_queue (decision_id) VALUES (%s)", (decisao_id,)
            )
        return decisao_id


def pending_reviews(limit: int = 50) -> list[dict]:
    if not enabled():
        return []
    with cursor() as cur:
        cur.execute(
            """
            SELECT q.id, d.score, d.band, t.amount, q.queued_at, d.explanation
            FROM review_queue q
            JOIN decisions d ON d.id = q.decision_id
            JOIN transactions t ON t.id = d.transaction_id
            WHERE q.status <> 'resolved'
            ORDER BY d.score DESC, q.queued_at
            LIMIT %s
            """,
            (limit,),
        )
        colunas = [c.name for c in cur.description]
        return [dict(zip(colunas, linha)) for linha in cur.fetchall()]


def resolve_review(review_id: int, is_fraud: bool, analyst: str) -> bool:
    """Fecha um caso da fila com o veredito humano."""
    if not enabled():
        return False
    with cursor() as cur:
        cur.execute(
            """
            UPDATE review_queue
               SET status = 'resolved', analyst_label = %s,
                   assigned_to = %s, resolved_at = now()
             WHERE id = %s AND status <> 'resolved'
            """,
            (is_fraud, analyst, review_id),
        )
        return cur.rowcount > 0


def review_precision(window_hours: int = 24) -> dict:
    """Camada 2 do monitoramento: precisão na faixa de revisão, em horas."""
    if not enabled():
        return {"available": False}
    with cursor() as cur:
        cur.execute(
            """
            SELECT count(*) FILTER (WHERE analyst_label) AS fraudes,
                   count(*)                              AS revisados
            FROM review_queue
            WHERE status = 'resolved' AND resolved_at > now() - make_interval(hours => %s)
            """,
            (window_hours,),
        )
        fraudes, revisados = cur.fetchone()
        return {
            "available": True,
            "window_hours": window_hours,
            "reviewed": int(revisados or 0),
            "confirmed_frauds": int(fraudes or 0),
            "precision": float(fraudes / revisados) if revisados else None,
        }
