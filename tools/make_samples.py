"""Extrai um recorte de transações reais do conjunto de teste para a simulação.

    python tools/make_samples.py

A imagem de serving não carrega o dataset — são 150 MB e ela não treina nada. Para que
a simulação use transações **reais e rotuladas**, com estrutura de correlação preservada
entre as componentes de PCA, um recorte pequeno é embutido na imagem.

Vem do conjunto de teste de propósito: são exatamente as transações que o modelo nunca
viu, e cujo rótulo permite verificar se a decisão exibida na tela está certa.
"""

from __future__ import annotations

import json

from src.ingestion import load_raw
from src.preprocessing import temporal_split
from src.utils import cfg, get_logger, load_config, resolve_path

logger = get_logger("amostras")

N_FRAUDES = 60
N_LEGITIMAS = 140


def main() -> int:
    config = load_config()
    bruto = load_raw()
    _, _, teste = temporal_split(
        bruto,
        cfg(config, "data.split.train_frac"),
        cfg(config, "data.split.val_frac"),
    )

    colunas = ["Time"] + [f"V{i}" for i in range(1, 29)] + ["Amount"]
    fraudes = teste[teste["Class"] == 1].head(N_FRAUDES)
    # Legítimas variadas em valor, para a simulação não parecer sempre igual.
    legitimas = (
        teste[teste["Class"] == 0]
        .sample(n=N_LEGITIMAS, random_state=cfg(config, "project.random_seed"))
        .sort_values("Amount")
    )

    registros = []
    for rotulo, frame in ((1, fraudes), (0, legitimas)):
        for _, linha in frame.iterrows():
            registros.append({
                "label": int(rotulo),
                "Time": float(linha["Time"]),
                "Amount": round(float(linha["Amount"]), 2),
                "V": [round(float(linha[f"V{i}"]), 6) for i in range(1, 29)],
            })

    destino = resolve_path("deploy/samples.json")
    destino.write_text(
        json.dumps(
            {
                "origem": "conjunto de teste — transações que o modelo nunca viu",
                "n_fraudes": len(fraudes),
                "n_legitimas": len(legitimas),
                "transacoes": registros,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    logger.info(
        "%d transações gravadas em %s (%.0f KB)",
        len(registros), destino.name, destino.stat().st_size / 1024,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
