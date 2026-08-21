"""Monitoramento em três camadas, ordenadas pela latência do sinal.

O que define o problema operacional aqui é que **o rótulo verdadeiro não existe no
momento da decisão**: ele chega quando o titular contesta a cobrança, dias ou meses
depois. Recall não é observável em tempo real, e propor um painel de recall diário
demonstraria desconhecimento da operação (ADR-0014).

Camada 1 — imediata, sem rótulo: PSI e KS das features, distribuição dos escores.
Camada 2 — horas: precisão na faixa de revisão manual, medida pelo analista.
Camada 3 — semanas: recall e custo confirmados por chargeback, só em janelas maduras.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from scipy.stats import ks_2samp

from src.utils import cfg, get_logger, load_config, resolve_path

logger = get_logger("drift_monitor")


def population_stability_index(
    referencia: np.ndarray, corrente: np.ndarray, n_bins: int = 10, epsilon: float = 1e-7
) -> float:
    """PSI entre duas distribuições, em faixas definidas pelos decis da referência.

    As faixas vêm da referência, não da amostra corrente: o objetivo é medir o quanto a
    corrente se afastou de um padrão fixo. Recalcular as faixas a cada janela mediria
    outra coisa a cada medição.
    """
    cortes = np.quantile(referencia, np.linspace(0, 1, n_bins + 1))
    cortes[0], cortes[-1] = -np.inf, np.inf
    cortes = np.unique(cortes)
    if len(cortes) < 3:
        return 0.0

    ref, _ = np.histogram(referencia, bins=cortes)
    cur, _ = np.histogram(corrente, bins=cortes)
    p_ref = np.maximum(ref / max(ref.sum(), 1), epsilon)
    p_cur = np.maximum(cur / max(cur.sum(), 1), epsilon)
    return float(np.sum((p_cur - p_ref) * np.log(p_cur / p_ref)))


def classify(psi: float, config) -> str:
    limites = cfg(config, "monitoring.psi.thresholds")
    if psi < limites["stable"]:
        return "stable"
    return "warning" if psi < limites["warning"] else "drift"


def compare(referencia: pd.DataFrame, corrente: pd.DataFrame, config=None) -> list[dict]:
    """PSI e KS por feature, ordenados por severidade."""
    config = config or load_config()
    n_bins = cfg(config, "monitoring.psi.n_bins")
    epsilon = cfg(config, "monitoring.psi.epsilon")

    linhas = []
    for coluna in referencia.columns:
        ref = referencia[coluna].to_numpy()
        cur = corrente[coluna].to_numpy()
        psi = population_stability_index(ref, cur, n_bins, epsilon)
        # Com centenas de milhares de linhas, o p-valor fica significativo para
        # diferenças irrelevantes: a magnitude da estatistica KS é o que orienta a
        # decisão, e o p-valor é contexto.
        ks = ks_2samp(ref, cur)
        linhas.append({
            "feature": coluna,
            "psi": round(psi, 6),
            "ks_statistic": round(float(ks.statistic), 6),
            "ks_pvalue": float(ks.pvalue),
            "severity": classify(psi, config),
        })
    return sorted(linhas, key=lambda linha: linha["psi"], reverse=True)


def simulate_shift(dados: pd.DataFrame, coluna: str, magnitude: float) -> pd.DataFrame:
    """Desloca uma feature em múltiplos do próprio desvio, para validar os alertas."""
    alterado = dados.copy()
    alterado[coluna] = alterado[coluna] + magnitude * alterado[coluna].std()
    return alterado


def run(X_train, X_test, top_features=None, config=None, save: bool = True) -> dict:
    config = config or load_config()

    # Drift real: treino contra teste são períodos distintos por construção do split
    # cronológico (ADR-0003), então qualquer diferença aqui é genuína.
    real = compare(X_train, X_test, config)
    relevantes = [linha for linha in real if linha["severity"] != "stable"]
    logger.info(
        "Drift real (treino → teste): %d de %d features fora de estável; pior PSI %.4f (%s)",
        len(relevantes), len(real), real[0]["psi"], real[0]["feature"],
    )

    # Drift simulado: valida que os indicadores respondem e que as faixas de alerta
    # separam o que deveriam separar.
    alvo = (top_features or list(X_train.columns))[0]
    simulacoes = []
    for magnitude in cfg(config, "monitoring.simulation.shift_magnitudes"):
        deslocado = simulate_shift(X_test, alvo, magnitude)
        psi = population_stability_index(
            X_train[alvo].to_numpy(), deslocado[alvo].to_numpy(),
            cfg(config, "monitoring.psi.n_bins"), cfg(config, "monitoring.psi.epsilon"),
        )
        simulacoes.append({
            "feature": alvo, "shift_in_std": magnitude,
            "psi": round(psi, 6), "severity": classify(psi, config),
        })
    logger.info(
        "Drift simulado em %s: PSI %s",
        alvo, " → ".join(f"{s['psi']:.3f}" for s in simulacoes),
    )

    gatilhos = cfg(config, "monitoring.triggers")
    monitoradas = set((top_features or [])[: gatilhos["psi_applies_to_top_n_shap"]])
    disparos = [
        linha for linha in real
        if linha["psi"] > gatilhos["psi_threshold"]
        and (not monitoradas or linha["feature"] in monitoradas)
    ]

    resumo = {
        "label_delay_note": (
            "Recall não é observável em tempo real: o rótulo verdadeiro só existe quando "
            "há chargeback, dias a meses depois. Além disso, transações bloqueadas nunca "
            "geram chargeback, então os rótulos disponíveis são enviesados por seleção — "
            "o modelo interfere na coleta do rótulo que serviria para avaliá-lo."
        ),
        "layers": {
            "1_immediate_no_label": "PSI e KS das features; distribuição dos escores; frações por faixa",
            "2_hours": "precisão na faixa de revisão manual e uso da capacidade",
            "3_weeks": "recall e custo confirmados por chargeback, apenas em janelas maduras",
        },
        "real_drift": real,
        "features_out_of_stable": len(relevantes),
        "simulated_drift": simulacoes,
        "retraining_triggers": gatilhos,
        "triggered": [linha["feature"] for linha in disparos],
    }

    if save:
        caminho = resolve_path(cfg(config, "paths.reports_dir")) / "drift_report.json"
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(json.dumps(resumo, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Relatório gravado em reports/drift_report.json")
    return resumo
