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
# Transações que o modelo encaminha para revisão manual. Precisam ser escolhidas de
# propósito: a faixa intermediária recebe cerca de 0,1% do volume — a política a
# dimensiona pela capacidade real de análise —, então um recorte aleatório de 200
# transações traz zero ou uma. Sem elas não há como demonstrar a faixa que a política
# de três faixas existe para produzir (ADR-0028).
N_REVISAO = 25


def _da_faixa_de_revisao(teste, colunas, config):
    """Transações do teste que o modelo atual encaminha para revisão manual.

    Carrega o artefato treinado. Se ainda não houver um — primeira execução, antes do
    primeiro treino — devolve vazio em vez de falhar: o recorte continua útil, apenas
    sem os casos de faixa intermediária.
    """
    try:
        from src.artifacts import load as load_artifact

        artefato = load_artifact(config=config)
    except Exception as erro:  # noqa: BLE001 — ausência de artefato não é erro fatal aqui
        logger.warning("Sem artefato treinado (%s); recorte sem casos de revisão.", erro)
        return teste.iloc[0:0]

    X = artefato["preprocessor"].transform(teste[colunas])
    bruto = artefato["model"].predict_proba(X)[:, 1].astype("float64")
    p = artefato["calibrator"].transform(bruto)
    limiares = artefato["policy"]
    na_faixa = (p >= limiares["t_low"]) & (p < limiares["t_high"])
    escolhidas = teste[na_faixa]
    logger.info(
        "Faixa de revisão: %d transações no teste (%.3f%%), %d fraudes",
        len(escolhidas), na_faixa.mean() * 100, int(escolhidas["Class"].sum()),
    )
    return escolhidas.head(N_REVISAO)


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

    # Seleção pela faixa que o modelo atribui hoje. A faixa NÃO é gravada aqui: quem a
    # calcula é a API, na carga, com o modelo que estiver embarcado. Gravá-la deixaria
    # o arquivo prometendo no botão algo que uma versão futura do modelo não cumpriria.
    revisao = _da_faixa_de_revisao(teste, colunas, config)

    registros = []
    for rotulo, frame in ((1, fraudes), (0, legitimas), (None, revisao)):
        for _, linha in frame.iterrows():
            registros.append({
                "label": int(linha["Class"]) if rotulo is None else int(rotulo),
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
                "n_faixa_de_revisao": len(revisao),
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
