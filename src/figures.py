"""Geração das figuras do relatório.

Todas as figuras saem de execução real do pipeline, nunca de valores digitados. Backend
não interativo de propósito: isto roda em contêiner e na esteira, sem display.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    precision_recall_curve,
    roc_auc_score,
    roc_curve,
)

from src.utils import cfg, get_logger, load_config, resolve_path

logger = get_logger("figures")

plt.rcParams.update({
    "figure.dpi": 130, "savefig.bbox": "tight", "font.size": 9,
    "axes.grid": True, "grid.alpha": 0.3, "axes.spines.top": False,
    "axes.spines.right": False,
})


def _salvar(fig, nome: str, config) -> Path:
    destino = resolve_path(cfg(config, "paths.figures_dir"))
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / f"{nome}.png"
    fig.savefig(caminho)
    plt.close(fig)
    return caminho


def curva_precision_recall(y, scores, config) -> Path:
    precisao, recall, _ = precision_recall_curve(y, scores)
    ap = average_precision_score(y, scores)
    taxa = float(np.mean(y))

    fig, ax = plt.subplots(figsize=(5, 4))
    ax.plot(recall, precisao, lw=2, label=f"Modelo (PR-AUC = {ap:.4f})")
    # A linha de referência é a taxa de positivos, não 0,5: com 0,17% de fraudes,
    # o classificador aleatório vive rente ao eixo.
    ax.axhline(taxa, ls="--", c="crimson", lw=1,
               label=f"Aleatório ({taxa:.4f})")
    ax.set_xlabel("Recall"); ax.set_ylabel("Precisão")
    ax.set_title("Curva Precision-Recall — conjunto de teste")
    ax.legend(loc="upper right", fontsize=8)
    return _salvar(fig, "01_curva_precision_recall", config)


def curva_roc(y, scores, config) -> Path:
    fpr, tpr, _ = roc_curve(y, scores)
    auc = roc_auc_score(y, scores)
    fig, ax = plt.subplots(figsize=(5, 4))
    ax.plot(fpr, tpr, lw=2, label=f"Modelo (ROC-AUC = {auc:.4f})")
    ax.plot([0, 1], [0, 1], ls="--", c="gray", lw=1, label="Aleatório")
    ax.set_xlabel("Taxa de falsos positivos"); ax.set_ylabel("Taxa de verdadeiros positivos")
    ax.set_title("Curva ROC — conjunto de teste")
    ax.legend(loc="lower right", fontsize=8)
    return _salvar(fig, "02_curva_roc", config)


def matriz_de_confusao(y, scores, limiar, config) -> Path:
    matriz = confusion_matrix(y, (scores >= limiar).astype(int), labels=[0, 1])
    fig, ax = plt.subplots(figsize=(4.2, 3.8))
    ax.imshow(matriz, cmap="Blues")
    ax.set_xticks([0, 1], ["legítima", "fraude"])
    ax.set_yticks([0, 1], ["legítima", "fraude"])
    ax.set_xlabel("Previsto"); ax.set_ylabel("Real")
    ax.set_title(f"Matriz de confusão (limiar = {limiar:.4f})")
    ax.grid(False)
    for i in range(2):
        for j in range(2):
            ax.text(j, i, f"{matriz[i, j]:,}".replace(",", "."), ha="center", va="center",
                    color="white" if matriz[i, j] > matriz.max() / 2 else "black",
                    fontsize=11, fontweight="bold")
    return _salvar(fig, "03_matriz_confusao", config)


def distribuicao_dos_escores(y, scores, thresholds, config) -> Path:
    y = np.asarray(y)
    fig, ax = plt.subplots(figsize=(5.5, 4))
    faixas = np.linspace(0, 1, 41)
    ax.hist(scores[y == 0], bins=faixas, alpha=0.65, label="legítimas", color="steelblue")
    ax.hist(scores[y == 1], bins=faixas, alpha=0.8, label="fraudes", color="crimson")
    ax.axvline(thresholds["t_low"], ls="--", c="darkorange", lw=1.4,
               label=f"t_low = {thresholds['t_low']:.3f}")
    ax.axvline(thresholds["t_high"], ls="--", c="darkred", lw=1.4,
               label=f"t_high = {thresholds['t_high']:.3f}")
    ax.set_yscale("log")
    ax.set_xlabel("Probabilidade calibrada"); ax.set_ylabel("Transações (escala log)")
    ax.set_title("Distribuição dos escores e faixas da política")
    ax.legend(fontsize=8)
    return _salvar(fig, "04_distribuicao_escores", config)


def diagrama_de_confiabilidade(y, bruto, calibrado, config, n_bins: int = 10) -> Path:
    fig, ax = plt.subplots(figsize=(5, 4.4))
    for escores, rotulo, cor in ((bruto, "bruto", "gray"), (calibrado, "calibrado", "seagreen")):
        cortes = np.quantile(escores, np.linspace(0, 1, n_bins + 1))
        cortes[0], cortes[-1] = -np.inf, np.inf
        indices = np.digitize(escores, cortes[1:-1])
        xs, ys = [], []
        for faixa in range(n_bins):
            m = indices == faixa
            if m.sum() < 5:
                continue
            xs.append(escores[m].mean()); ys.append(np.asarray(y)[m].mean())
        ax.plot(xs, ys, "o-", ms=4, color=cor, label=rotulo)
    ax.plot([0, 1], [0, 1], ls="--", c="black", lw=1, label="calibração perfeita")
    ax.set_xlabel("Probabilidade prevista"); ax.set_ylabel("Frequência observada")
    ax.set_title("Diagrama de confiabilidade")
    ax.legend(fontsize=8)
    return _salvar(fig, "05_diagrama_confiabilidade", config)


def sensibilidade(linhas: list[dict], config) -> Path:
    """Mapa de calor do custo sob variação das premissas.

    A conclusão que interessa é o comportamento da política sob variação, não o par de
    limiares obtido com um conjunto arbitrado de custos (ADR-0010).
    """
    viaveis = [linha for linha in linhas if not linha.get("infeasible")]
    if not viaveis:
        return None
    razoes = sorted({linha["cost_ratio"] for linha in viaveis})
    capacidades = sorted({linha["capacity"] for linha in viaveis})
    grade = np.full((len(razoes), len(capacidades)), np.nan)
    for linha in viaveis:
        grade[razoes.index(linha["cost_ratio"]), capacidades.index(linha["capacity"])] = \
            linha["total_cost"]

    fig, ax = plt.subplots(figsize=(5.6, 4))
    im = ax.imshow(grade, cmap="RdYlGn_r", aspect="auto")
    ax.set_xticks(range(len(capacidades)), [f"{c:.2%}" for c in capacidades], rotation=45)
    ax.set_yticks(range(len(razoes)), [f"{r}×" for r in razoes])
    ax.set_xlabel("Capacidade de revisão manual")
    ax.set_ylabel("Custo do bloqueio indevido ÷ custo da revisão")
    ax.set_title("Custo total esperado sob variação das premissas")
    ax.grid(False)
    fig.colorbar(im, ax=ax, label="custo total")
    for i in range(len(razoes)):
        for j in range(len(capacidades)):
            if not np.isnan(grade[i, j]):
                ax.text(j, i, f"{grade[i, j]:.0f}", ha="center", va="center", fontsize=7)
    return _salvar(fig, "06_sensibilidade_custos", config)


def drift(linhas: list[dict], config, top: int = 15) -> Path:
    piores = linhas[:top]
    cores = {"stable": "seagreen", "warning": "goldenrod", "drift": "crimson"}
    fig, ax = plt.subplots(figsize=(5.6, 4.4))
    nomes = [linha["feature"] for linha in piores][::-1]
    valores = [linha["psi"] for linha in piores][::-1]
    ax.barh(nomes, valores, color=[cores[l["severity"]] for l in piores][::-1])
    limites = cfg(config, "monitoring.psi.thresholds")
    ax.axvline(limites["stable"], ls="--", c="goldenrod", lw=1, label="atenção (0,10)")
    ax.axvline(limites["warning"], ls="--", c="crimson", lw=1, label="drift (0,25)")
    ax.set_xscale("log")
    ax.set_xlabel("PSI (escala log)")
    ax.set_title("Drift entre treino e teste, por atributo")
    ax.legend(fontsize=8)
    return _salvar(fig, "07_drift_psi", config)


def importancia_shap(ranking: dict, config, top: int = 15) -> Path:
    itens = list(ranking.items())[:top][::-1]
    fig, ax = plt.subplots(figsize=(5.2, 4.4))
    ax.barh([k for k, _ in itens], [v for _, v in itens], color="slateblue")
    ax.set_xlabel("Contribuição média absoluta (SHAP)")
    ax.set_title("Atributos mais influentes")
    return _salvar(fig, "08_importancia_shap", config)
