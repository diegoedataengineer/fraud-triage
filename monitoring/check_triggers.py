"""Avalia os gatilhos de retreino e diz se algum disparou.

    python -m monitoring.check_triggers            # relatório legível
    python -m monitoring.check_triggers --json     # saída para máquina
    python -m monitoring.check_triggers --exit-code # 10 se algum disparou

Os três gatilhos estão definidos em `monitoring.triggers` (ADR-0014, Spec 005). Até a
versão 1.5.0 eles existiam apenas como configuração: o PSI era calculado e gravado no
relatório de drift, os outros dois não eram avaliados por código nenhum, e **ninguém
consumia o resultado**. Este módulo fecha essa lacuna (ADR-0030).

O que ele **não** faz: decidir promover. Um disparo manda treinar um candidato; publicar
em produção continua exigindo que uma pessoa mescle o Release PR. Em detecção de fraude,
promover modelo sem revisão humana troca um risco conhecido por um desconhecido.

Cada gatilho declara a própria disponibilidade de dado. Um gatilho que não pôde ser
avaliado aparece como `sem dados` — nunca como "não disparou", que afirmaria algo que não
foi verificado.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

from src.utils import cfg, get_logger, load_config, resolve_path

logger = get_logger("gatilhos")

SEM_DADOS = "sem dados"
DISPAROU = "disparou"
ESTAVEL = "estável"


def _psi(config) -> dict:
    """Camada 1: deslocamento de distribuição, imediato e sem rótulo.

    Lê o que `drift_monitor` já apurou. Importante para quem for interpretar: no relatório
    gerado pelo pipeline a comparação é **treino contra teste**, não tráfego de produção
    contra a referência de treino. É a demonstração do mecanismo sobre os dados que
    existem, e confirma que a base é não estacionária — mas não é sinal de produção, e
    dizer que é seria falsear a evidência.
    """
    gatilhos = cfg(config, "monitoring.triggers")
    caminho = resolve_path(cfg(config, "paths.reports_dir")) / "drift_report.json"
    if not caminho.exists():
        return {"nome": "psi", "estado": SEM_DADOS, "limiar": gatilhos["psi_threshold"],
                "detalhe": "reports/drift_report.json ausente — rode o pipeline"}

    relatorio = json.loads(caminho.read_text(encoding="utf-8"))
    disparados = relatorio.get("triggered") or []
    return {
        "nome": "psi",
        "estado": DISPAROU if disparados else ESTAVEL,
        "limiar": gatilhos["psi_threshold"],
        "valor": len(disparados),
        "detalhe": (
            f"{len(disparados)} atributo(s) acima de {gatilhos['psi_threshold']}: "
            f"{', '.join(disparados)}" if disparados else "nenhum atributo acima do limiar"
        ),
        "origem": "treino × teste (não é tráfego de produção)",
    }


def _idade(config, treinado_em: str | None) -> dict:
    """Agenda: retreinar a cada N dias, mesmo sem sinal de drift.

    Existe porque os dois outros gatilhos dependem de observar algo. A agenda não depende
    de nada, e é a rede de segurança para a deterioração lenta que nenhum limiar pega.
    """
    gatilhos = cfg(config, "monitoring.triggers")
    limite = gatilhos["scheduled_retrain_days"]
    carimbo = treinado_em

    if carimbo is None:
        try:
            from src.artifacts import load as carregar

            carimbo = carregar(config=config)["metadata"].get("created_at")
        except Exception:  # noqa: BLE001 — ausência de artefato é caso previsto, não erro
            carimbo = None

    if not carimbo:
        return {"nome": "agenda", "estado": SEM_DADOS, "limiar": limite,
                "detalhe": "sem artefato local e sem --treinado-em"}

    quando = datetime.fromisoformat(carimbo.replace("Z", "+00:00"))
    if quando.tzinfo is None:
        quando = quando.replace(tzinfo=timezone.utc)
    dias = (datetime.now(timezone.utc) - quando).days
    return {
        "nome": "agenda",
        "estado": DISPAROU if dias >= limite else ESTAVEL,
        "limiar": limite,
        "valor": dias,
        "detalhe": f"treinado há {dias} dia(s); limite de {limite}",
        "origem": carimbo,
    }


def _precisao_da_revisao(config) -> dict:
    """Camada 2: precisão na fila de revisão, o único rótulo que chega em horas.

    Compara a precisão observada com a que o modelo registrou no próprio metadata. Sem
    banco configurado não há série nenhuma, e o gatilho fica `sem dados` — que é
    diferente de estável.
    """
    gatilhos = cfg(config, "monitoring.triggers")
    queda_max = gatilhos["manual_review_precision_drop"]

    if not os.environ.get("DATABASE_URL"):
        return {"nome": "precisao_revisao", "estado": SEM_DADOS, "limiar": queda_max,
                "detalhe": "DATABASE_URL não configurada — sem série para comparar"}

    from src import db

    # enabled() apenas confere a variável de ambiente; o pool só existe depois de init().
    # Sem isto a consulta levanta "Banco não inicializado" em vez de responder.
    if not db.init():
        return {"nome": "precisao_revisao", "estado": SEM_DADOS, "limiar": queda_max,
                "detalhe": "não foi possível conectar ao banco"}

    observado = db.review_precision(window_hours=24 * 7)
    if not observado.get("available") or not observado.get("reviewed"):
        return {"nome": "precisao_revisao", "estado": SEM_DADOS, "limiar": queda_max,
                "detalhe": "nenhum caso resolvido na janela de 7 dias"}

    resumo = resolve_path(cfg(config, "paths.reports_dir")) / "evaluation_summary.json"
    if not resumo.exists():
        return {"nome": "precisao_revisao", "estado": SEM_DADOS, "limiar": queda_max,
                "detalhe": "sem evaluation_summary.json para servir de referência"}
    dados = json.loads(resumo.read_text(encoding="utf-8"))
    referencia = dados["models"][dados["adopted_model"]]["test"]["precision"]

    atual = observado["precision"]
    queda = referencia - atual
    return {
        "nome": "precisao_revisao",
        "estado": DISPAROU if queda >= queda_max else ESTAVEL,
        "limiar": queda_max,
        "valor": round(queda, 4),
        "detalhe": (
            f"precisão {atual:.4f} contra referência {referencia:.4f} "
            f"(queda de {queda:.4f}; limite {queda_max})"
        ),
        "origem": f"{observado['reviewed']} caso(s) resolvido(s) em 7 dias",
    }


def avaliar(config=None, treinado_em: str | None = None) -> dict:
    config = config or load_config()
    gatilhos = [_psi(config), _idade(config, treinado_em), _precisao_da_revisao(config)]
    disparados = [g["nome"] for g in gatilhos if g["estado"] == DISPAROU]
    return {
        "retreinar": bool(disparados),
        "disparados": disparados,
        "gatilhos": gatilhos,
        "nota": (
            "Um disparo manda treinar um candidato. Promover para produção continua "
            "exigindo revisão humana (ADR-0030)."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Avalia os gatilhos de retreino.")
    parser.add_argument("--json", action="store_true", help="saída em JSON")
    parser.add_argument(
        "--exit-code", action="store_true",
        help="devolve 10 quando algum gatilho dispara, para uso em automação",
    )
    parser.add_argument(
        "--treinado-em",
        help="carimbo ISO de quando o modelo em produção foi treinado; "
             "usado quando não há artefato local",
    )
    args = parser.parse_args()

    resultado = avaliar(treinado_em=args.treinado_em)

    if args.json:
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
    else:
        marca = {DISPAROU: "🔴", ESTAVEL: "✅", SEM_DADOS: "⚪"}
        for g in resultado["gatilhos"]:
            logger.info("%s %-18s %-9s · %s",
                        marca[g["estado"]], g["nome"], g["estado"], g["detalhe"])
        if resultado["retreinar"]:
            logger.info("→ retreino indicado por: %s", ", ".join(resultado["disparados"]))
        else:
            logger.info("→ nenhum gatilho disparou")

    if args.exit_code and resultado["retreinar"]:
        return 10
    return 0


if __name__ == "__main__":
    sys.exit(main())
