"""Porta de qualidade: reprova a build se as métricas mínimas não forem atingidas.

Usado em dois pontos independentes da esteira — ao final do treino em homologação, e de
novo na promoção, lendo o metadata de dentro da imagem (Spec 007).
"""

from __future__ import annotations

import argparse
import json
import sys

from src.utils import cfg, get_logger, load_config, resolve_path

logger = get_logger("verify_minimums")


def check(metrics: dict, config=None) -> tuple[bool, dict]:
    config = config or load_config()
    minimos = cfg(config, "evaluation.rubric_minimums")
    faltas = {
        nome: {"obtido": metrics.get(nome), "minimo": piso}
        for nome, piso in minimos.items()
        if metrics.get(nome) is None or metrics[nome] < piso
    }
    return (not faltas), faltas


def main() -> int:
    parser = argparse.ArgumentParser(description="Verifica os mínimos da rubrica.")
    parser.add_argument(
        "--from-metadata", action="store_true",
        help="lê as métricas do metadata.json do artefato, em vez do relatório de avaliação",
    )
    parser.add_argument("--path", help="caminho explícito do JSON a inspecionar")
    args = parser.parse_args()

    config = load_config()
    if args.path:
        origem = resolve_path(args.path)
        metricas = json.loads(origem.read_text(encoding="utf-8")).get("metrics", {})
    elif args.from_metadata:
        from src.artifacts import load as load_artifact
        artefato = load_artifact(config=config)
        origem, metricas = artefato["path"], artefato["metadata"]["metrics"]
    else:
        origem = resolve_path(cfg(config, "paths.reports_dir")) / "evaluation_summary.json"
        resumo = json.loads(origem.read_text(encoding="utf-8"))
        metricas = resumo["models"][resumo["adopted_model"]]["test"]

    ok, faltas = check(metricas, config)
    logger.info("Verificando mínimos a partir de %s", origem)
    if ok:
        for nome, piso in cfg(config, "evaluation.rubric_minimums").items():
            logger.info("  ✅ %-10s %.4f ≥ %.2f", nome, metricas[nome], piso)
        return 0

    for nome, detalhe in faltas.items():
        logger.error("  ❌ %-10s %.4f < %.2f", nome, detalhe["obtido"] or 0.0, detalhe["minimo"])
    logger.error("Mínimos da rubrica não atingidos — build reprovada.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
