"""API de inferência: modelo, calibrador e política de três faixas atrás de HTTP.

Persistência é opcional por configuração: sem `DATABASE_URL` a API responde normalmente
e não grava. Degradar em vez de falhar é deliberado — exigir banco para responder uma
inferência tornaria a avaliação mais frágil sem tornar o modelo melhor (ADR-0018).
"""

from __future__ import annotations

import os
import json
import random
import time
from collections import Counter, deque
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src import __version__, artifacts, db
from src.utils import cfg, get_logger, load_config

logger = get_logger("api")

app = FastAPI(
    title="Triagem de Fraude",
    description=(
        "Decide transações de cartão de crédito em três faixas — aprovar, encaminhar "
        "para revisão manual ou bloquear — sobre a probabilidade calibrada de fraude.\n\n"
        "Use `?trace=true` em `/predict` para receber os valores intermediários de cada "
        "etapa do pipeline, com o tempo gasto em cada uma."
    ),
    # Derivada de src/__init__.py, atualizada pelo release-please. Fixá-la aqui fazia a
    # documentação da API divergir do modelo servido a cada promoção de versão.
    version=__version__,
)

# O painel roda em outra origem (servidor estático), entao precisa de CORS. Aberto
# porque o ecossistema sobe inteiro em localhost, para demonstracao — em producao a
# origem seria restrita ao dominio do console.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

ESTADO: dict[str, Any] = {}

# Contadores em memoria: mantem /stats util mesmo sem banco, preservando o caminho
# de avaliacao com um unico comando (ADR-0018).
CONTAGEM: dict[str, int] = {"approve": 0, "manual_review": 0, "block": 0}

# Janela deslizante das latencias de inferencia. Limitada de proposito: o interesse e
# o comportamento recente do servico, nao a media desde que ele subiu — uma media
# eterna esconde degradacao, que e justamente o que se quer enxergar.
LATENCIAS: deque[float] = deque(maxlen=500)


def _percentil(valores: list[float], q: float) -> float:
    """Percentil por interpolacao linear, sem trazer numpy para o caminho de resposta."""
    if not valores:
        return 0.0
    ordenado = sorted(valores)
    if len(ordenado) == 1:
        return ordenado[0]
    pos = q * (len(ordenado) - 1)
    baixo = int(pos)
    resto = pos - baixo
    if baixo + 1 >= len(ordenado):
        return ordenado[-1]
    return ordenado[baixo] + resto * (ordenado[baixo + 1] - ordenado[baixo])


class Transaction(BaseModel):
    """Transação no mesmo formato do dataset: Time, V1–V28 e Amount."""

    Time: float = Field(..., ge=0, description="segundos desde a primeira transação")
    Amount: float = Field(..., ge=0, description="valor da transação")
    V: list[float] = Field(..., min_length=28, max_length=28,
                           description="componentes de PCA V1–V28")


class Decision(BaseModel):
    probability: float
    band: str
    action: str
    thresholds: dict[str, float]
    model_version: str
    decision_id: int | None = None
    trace: list[dict] | None = None


ACOES = {
    "approve": "aprovar automaticamente",
    "manual_review": "encaminhar para revisão manual",
    "block": "bloquear automaticamente",
}


@app.on_event("startup")
def carregar() -> None:
    """Carrega o artefato uma vez, na inicialização — nunca por requisição."""
    config = load_config()
    artefato = artifacts.load(config=config)
    ESTADO.update(artefato)
    ESTADO["config"] = config
    amostras = Path(__file__).resolve().parent / "samples.json"
    ESTADO["samples"] = (
        json.loads(amostras.read_text(encoding="utf-8"))["transacoes"]
        if amostras.exists() else []
    )
    _classificar_amostras()
    ESTADO["persist"] = db.init()
    if ESTADO["persist"]:
        db.register_model(artefato["metadata"])
    logger.info(
        "Modelo %s carregado de %s · persistência: %s",
        artefato["metadata"]["version"], artefato["path"],
        "ativa" if ESTADO["persist"] else "desativada (sem DATABASE_URL)",
    )


def _classificar_amostras() -> None:
    """Anota cada amostra embutida com a faixa que o modelo lhe atribui.

    A faixa é calculada aqui, na carga, e não gravada no arquivo de amostras. A razão
    é de consistência: o arquivo é versionado no repositório e o modelo muda a cada
    release, então uma faixa pré-calculada envelheceria em silêncio e passaria a
    prometer no botão algo diferente do que a API decidiria.

    Existe para que a faixa de **revisão manual** seja demonstrável. Ela é rara por
    construção — a política a dimensiona pela capacidade real de análise, e no teste
    ela recebe cerca de 0,1% das transações. Sorteando ao acaso seriam necessárias
    centenas de tentativas para ver uma, e a faixa intermediária é justamente o que a
    política de três faixas existe para produzir.
    """
    amostras = ESTADO.get("samples") or []
    if not amostras:
        return
    linhas = [
        {**{f"V{i}": v for i, v in enumerate(a["V"], start=1)},
         "Time": a["Time"], "Amount": a["Amount"]}
        for a in amostras
    ]
    X = ESTADO["preprocessor"].transform(pd.DataFrame(linhas))
    bruto = ESTADO["model"].predict_proba(X)[:, 1].astype(np.float64)
    p = ESTADO["calibrator"].transform(bruto)
    limiares = ESTADO["policy"]
    for amostra, valor in zip(amostras, p):
        amostra["band"] = (
            "block" if valor >= limiares["t_high"]
            else "manual_review" if valor >= limiares["t_low"]
            else "approve"
        )
    contagem = Counter(a["band"] for a in amostras)
    logger.info(
        "Amostras classificadas · %s",
        " · ".join(f"{k}: {v}" for k, v in sorted(contagem.items())),
    )


@app.get("/health")
def health() -> dict:
    if not ESTADO:
        raise HTTPException(status_code=503, detail="modelo ainda não carregado")
    meta = ESTADO["metadata"]
    return {
        "status": "ok",
        "model_version": meta["version"],
        "git_sha": meta["git_sha"],
        "metrics": meta["metrics"],
        "persistence": ESTADO["persist"],
    }


@app.post("/predict", response_model=Decision)
def predict(transacao: Transaction, trace: bool = Query(False)) -> Decision:
    """Decide uma transação. Com `trace=true`, devolve também os valores intermediários.

    O rastro existe para tornar o caminho auditável: sem ele, o serviço é uma caixa que
    devolve um número, e não há como mostrar — nem conferir — o que aconteceu entre a
    transação recebida e a faixa decidida.
    """
    if not ESTADO:
        raise HTTPException(status_code=503, detail="modelo ainda não carregado")

    passos: list[dict] = []
    marco = time.perf_counter()

    def registrar(nome: str, detalhe: dict) -> None:
        nonlocal marco
        agora = time.perf_counter()
        passos.append({
            "step": nome, "detail": detalhe, "ms": round((agora - marco) * 1000, 3)
        })
        marco = agora

    linha = {f"V{i}": v for i, v in enumerate(transacao.V, start=1)}
    linha["Time"] = transacao.Time
    linha["Amount"] = transacao.Amount
    frame = pd.DataFrame([linha])
    registrar("entrada", {
        "atributos_recebidos": len(linha),
        "Amount": transacao.Amount,
        "Time": transacao.Time,
        "V1_V3": [round(v, 4) for v in transacao.V[:3]],
    })

    # Mesma transformação do treino, reusando o objeto persistido — jamais reajustada.
    X = ESTADO["preprocessor"].transform(frame)
    derivados = {
        c: round(float(X.iloc[0][c]), 6)
        for c in ("Amount_log", "Hour", "Amount_zscore_by_hour") if c in X.columns
    }
    registrar("pre_processamento", {
        "atributos_gerados": int(X.shape[1]),
        "derivados": derivados,
        "Time_descartado": True,
    })

    bruto = ESTADO["model"].predict_proba(X)[:, 1].astype(np.float64)
    registrar("modelo", {
        "estimador": type(ESTADO["model"]).__name__,
        "escore_bruto": round(float(bruto[0]), 8),
    })

    probabilidade = float(ESTADO["calibrator"].transform(bruto)[0])
    registrar("calibracao", {
        "metodo": getattr(ESTADO["calibrator"], "method", "?"),
        "escore_bruto": round(float(bruto[0]), 8),
        "probabilidade_calibrada": round(probabilidade, 8),
    })

    limiares = ESTADO["policy"]
    if probabilidade >= limiares["t_high"]:
        faixa = "block"
    elif probabilidade >= limiares["t_low"]:
        faixa = "manual_review"
    else:
        faixa = "approve"
    registrar("politica", {
        "t_low": limiares["t_low"], "t_high": limiares["t_high"],
        "comparacao": (
            f"{probabilidade:.6f} >= {limiares['t_high']}" if faixa == "block"
            else f"{limiares['t_low']} <= {probabilidade:.6f} < {limiares['t_high']}"
            if faixa == "manual_review"
            else f"{probabilidade:.6f} < {limiares['t_low']}"
        ),
        "faixa": faixa,
    })

    CONTAGEM[faixa] += 1

    decisao_id = None
    if ESTADO["persist"]:
        decisao_id = db.record_decision(
            features=linha,
            amount=transacao.Amount,
            occurred_at_seconds=transacao.Time,
            version=ESTADO["metadata"]["version"],
            score=probabilidade,
            band=faixa,
            thresholds=limiares,
            explanation=None,
        )

    registrar("persistencia", {
        "ativa": ESTADO["persist"],
        "decision_id": decisao_id,
        "enfileirado_para_revisao": faixa == "manual_review",
    })

    total_ms = round(sum(p["ms"] for p in passos), 3)
    LATENCIAS.append(total_ms)
    passos.append({"step": "total", "detail": {"etapas": len(passos)}, "ms": total_ms})

    return Decision(
        probability=probabilidade,
        band=faixa,
        action=ACOES[faixa],
        thresholds=limiares,
        model_version=ESTADO["metadata"]["version"],
        decision_id=decisao_id,
        trace=passos if trace else None,
    )


class ReviewVerdict(BaseModel):
    is_fraud: bool = Field(..., description="veredito do analista")
    analyst: str = Field("analista", description="quem revisou")


@app.get("/review/queue")
def fila_de_revisao(limit: int = 50) -> dict:
    """Fila de revisão manual, ordenada pelo escore.

    É a faixa do meio da política de três faixas. Também é o único ponto do sistema
    que produz rótulo em horas: o rótulo verdadeiro por chargeback leva semanas
    (ADR-0014).
    """
    if not ESTADO.get("persist"):
        raise HTTPException(
            status_code=503,
            detail="fila indisponível: a API está sem DATABASE_URL configurada",
        )
    itens = db.pending_reviews(limit)
    return {"pending": len(itens), "items": itens}


@app.post("/review/{review_id}/resolve")
def resolver_revisao(review_id: int, veredito: ReviewVerdict) -> dict:
    if not ESTADO.get("persist"):
        raise HTTPException(status_code=503, detail="fila indisponível sem DATABASE_URL")
    if not db.resolve_review(review_id, veredito.is_fraud, veredito.analyst):
        raise HTTPException(status_code=404, detail="caso inexistente ou já resolvido")
    return {"review_id": review_id, "status": "resolved", "is_fraud": veredito.is_fraud}


@app.get("/monitoring/review-precision")
def precisao_da_revisao(window_hours: int = 24) -> dict:
    """Camada 2 do monitoramento: o sinal de qualidade mais rápido disponível."""
    if not ESTADO.get("persist"):
        raise HTTPException(status_code=503, detail="indisponível sem DATABASE_URL")
    return db.review_precision(window_hours)


@app.get("/simulate/sample")
def amostra(
    kind: str = Query("random", pattern="^(random|fraud|legitimate|review|block)$"),
) -> dict:
    """Devolve uma transação real do conjunto de teste, para alimentar a simulação.

    São transações que o modelo nunca viu, com rótulo conhecido — o que permite
    verificar na tela se a decisão exibida está correta. Gerar sinteticamente não
    serviria: marginais independentes não preservam a correlação entre as componentes
    de PCA, e o modelo responderia a um dado que não existe.
    """
    amostras = ESTADO.get("samples") or []
    if not amostras:
        raise HTTPException(status_code=503, detail="amostras não embutidas nesta imagem")

    filtradas = amostras
    if kind == "fraud":
        filtradas = [a for a in amostras if a["label"] == 1]
    elif kind == "legitimate":
        filtradas = [a for a in amostras if a["label"] == 0]
    elif kind in ("review", "block"):
        # Seleção pela faixa que o modelo atribui, não pelo rótulo: é o que permite
        # demonstrar a faixa intermediária, rara demais para aparecer por sorteio.
        alvo = "manual_review" if kind == "review" else "block"
        filtradas = [a for a in amostras if a.get("band") == alvo]
        if not filtradas:
            raise HTTPException(
                status_code=404,
                detail=f"nenhuma amostra embutida cai na faixa '{alvo}' neste modelo",
            )

    escolhida = random.choice(filtradas)
    return {
        "transaction": {k: escolhida[k] for k in ("Time", "Amount", "V")},
        "true_label": escolhida["label"],
        "is_fraud": bool(escolhida["label"]),
        "expected_band": escolhida.get("band"),
    }


@app.get("/stats")
def estatisticas() -> dict:
    """Painel de operação: versão em uso, limiares e o que já passou pelo sistema."""
    if not ESTADO:
        raise HTTPException(status_code=503, detail="modelo ainda não carregado")
    total = sum(CONTAGEM.values())
    amostras = list(LATENCIAS)
    return {
        "latency": {
            "n": len(amostras),
            "last_ms": round(amostras[-1], 3) if amostras else None,
            "mean_ms": round(sum(amostras) / len(amostras), 3) if amostras else None,
            "p50_ms": round(_percentil(amostras, 0.50), 3) if amostras else None,
            "p95_ms": round(_percentil(amostras, 0.95), 3) if amostras else None,
            "max_ms": round(max(amostras), 3) if amostras else None,
            "janela": LATENCIAS.maxlen,
        },
        "model_version": ESTADO["metadata"]["version"],
        "thresholds": ESTADO["policy"],
        "metrics": ESTADO["metadata"]["metrics"],
        "persistence": ESTADO["persist"],
        "processed": total,
        "bands": CONTAGEM,
        "band_fractions": {
            k: (v / total if total else 0.0) for k, v in CONTAGEM.items()
        },
        "review": db.review_precision() if ESTADO["persist"] else {"available": False},
    }


def main() -> None:
    import uvicorn

    config = load_config()
    uvicorn.run(
        app,
        host=os.environ.get("API_HOST", cfg(config, "serving.host")),
        port=int(os.environ.get("API_PORT", cfg(config, "serving.port"))),
        log_level="info",
    )


if __name__ == "__main__":
    main()
