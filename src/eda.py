"""Análise exploratória dos dados brutos.

Roda **fora** do pipeline de retreino: é etapa de entendimento, não de produção. Todas
as estatísticas saem da base real e alimentam a seção de análise do relatório.

Uma observação metodológica: a EDA olha a base inteira, porque seu objetivo é descrever
o fenômeno. Nenhuma decisão de modelagem é tomada aqui — as estatísticas que entram no
pré-processamento são estimadas apenas no treino (ADR-0003).
"""

from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from src.figures import _salvar
from src.ingestion import load_raw
from src.utils import cfg, get_logger, load_config, resolve_path, timed

logger = get_logger("eda")


def run(save: bool = True) -> dict:
    config = load_config()
    with timed(logger, "Análise exploratória"):
        df = load_raw()
        alvo = cfg(config, "features.target_col")
        fraudes = df[df[alvo] == 1]
        legitimas = df[df[alvo] == 0]

        # ── desequilíbrio de classes ──────────────────────────────────────────
        fig, ax = plt.subplots(figsize=(4.6, 3.6))
        contagens = [len(legitimas), len(fraudes)]
        ax.bar(["legítimas", "fraudes"], contagens, color=["steelblue", "crimson"])
        ax.set_yscale("log")
        ax.set_ylabel("Transações (escala log)")
        ax.set_title(f"Desequilíbrio de classes — {100*df[alvo].mean():.4f}% de fraudes")
        for i, v in enumerate(contagens):
            ax.text(i, v, f"{v:,}".replace(",", "."), ha="center", va="bottom", fontsize=9)
        _salvar(fig, "00a_desequilibrio_classes", config)

        # ── valor da transação ────────────────────────────────────────────────
        fig, ax = plt.subplots(figsize=(5.4, 3.8))
        faixas = np.logspace(-2, np.log10(df.Amount.max() + 1), 50)
        ax.hist(legitimas.Amount + 0.01, bins=faixas, alpha=0.6,
                label="legítimas", color="steelblue", density=True)
        ax.hist(fraudes.Amount + 0.01, bins=faixas, alpha=0.75,
                label="fraudes", color="crimson", density=True)
        ax.set_xscale("log")
        ax.set_xlabel("Valor (R$, escala log)"); ax.set_ylabel("Densidade")
        ax.set_title("Distribuição do valor por classe")
        ax.legend(fontsize=8)
        _salvar(fig, "00b_distribuicao_valor", config)

        # ── comportamento ao longo das 48 horas ───────────────────────────────
        hora = (df.Time / 3600).astype(int)
        por_hora = df.groupby(hora)[alvo].agg(["mean", "size"])
        fig, (a1, a2) = plt.subplots(2, 1, figsize=(6.4, 4.6), sharex=True)
        a1.plot(por_hora.index, por_hora["size"], color="steelblue")
        a1.set_ylabel("Transações"); a1.set_title("Volume e taxa de fraude nas 48 horas")
        a2.plot(por_hora.index, 100 * por_hora["mean"], color="crimson")
        a2.set_ylabel("Fraudes (%)"); a2.set_xlabel("Hora desde a primeira transação")
        _salvar(fig, "00c_comportamento_temporal", config)

        # ── quais componentes separam as classes ──────────────────────────────
        colunas_v = [f"V{i}" for i in range(1, 29)]
        separacao = (
            (fraudes[colunas_v].mean() - legitimas[colunas_v].mean()).abs()
            / df[colunas_v].std()
        ).sort_values(ascending=False)
        fig, ax = plt.subplots(figsize=(5.2, 4.2))
        itens = separacao.head(15)[::-1]
        ax.barh(itens.index, itens.values, color="slateblue")
        ax.set_xlabel("Separação entre classes (diferença de médias ÷ desvio)")
        ax.set_title("Componentes que mais distinguem fraude")
        _salvar(fig, "00d_separacao_componentes", config)

        duplicatas = int(df.duplicated().sum())
        resumo = {
            "n_rows": int(len(df)),
            "n_features": int(df.shape[1]),
            "n_frauds": int(len(fraudes)),
            "fraud_rate": float(df[alvo].mean()),
            "imbalance_ratio": f"1:{len(legitimas)//max(len(fraudes),1)}",
            "nulls": int(df.isna().sum().sum()),
            "exact_duplicates": duplicatas,
            "time_span_hours": float((df.Time.max() - df.Time.min()) / 3600),
            "amount": {
                "geral": {"min": float(df.Amount.min()), "mediana": float(df.Amount.median()),
                          "media": float(df.Amount.mean()), "max": float(df.Amount.max())},
                "fraudes": {"mediana": float(fraudes.Amount.median()),
                            "media": float(fraudes.Amount.mean()),
                            "max": float(fraudes.Amount.max())},
                "legitimas": {"mediana": float(legitimas.Amount.median()),
                              "media": float(legitimas.Amount.mean())},
            },
            "top_separating_components": separacao.head(10).round(4).to_dict(),
            "fraud_loss_total": float(fraudes.Amount.sum()),
        }

    logger.info(
        "%d linhas · %d fraudes (%.4f%%, razão %s) · %d duplicatas · %.1f h",
        resumo["n_rows"], resumo["n_frauds"], 100 * resumo["fraud_rate"],
        resumo["imbalance_ratio"], duplicatas, resumo["time_span_hours"],
    )
    logger.info(
        "Valor mediano — fraudes R$ %.2f · legítimas R$ %.2f · perda total R$ %.2f",
        resumo["amount"]["fraudes"]["mediana"],
        resumo["amount"]["legitimas"]["mediana"],
        resumo["fraud_loss_total"],
    )

    if save:
        caminho = resolve_path(cfg(config, "paths.reports_dir")) / "eda_summary.json"
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(json.dumps(resumo, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Resumo gravado em reports/eda_summary.json")
    return resumo


if __name__ == "__main__":
    run()
