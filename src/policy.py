"""Política de triagem em três faixas com restrição de capacidade de revisão.

Um classificador binário assume que a única resposta a uma transação suspeita é
bloquear ou liberar. Nenhuma operação antifraude funciona assim: existe uma fila de
revisão manual, ela é o instrumento central da operação, e ela é finita (ADR-0010).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict

import numpy as np

from src.utils import cfg, get_logger, load_config, resolve_path

logger = get_logger("policy")


@dataclass
class Policy:
    t_low: float
    t_high: float

    def apply(self, probabilities: np.ndarray) -> np.ndarray:
        """Devolve a faixa de cada transação."""
        faixas = np.full(len(probabilities), "approve", dtype=object)
        faixas[probabilities >= self.t_low] = "manual_review"
        faixas[probabilities >= self.t_high] = "block"
        return faixas


def expected_cost(
    y_true: np.ndarray, probabilities: np.ndarray, amounts: np.ndarray,
    t_low: float, t_high: float, costs: dict,
) -> dict:
    """Custo total esperado da política, em unidades monetárias.

    Fraudes na faixa de revisão são consideradas detectadas — premissa de revisão
    perfeita, declarada no relatório por ser otimista.
    """
    aprovadas = probabilities < t_low
    revisadas = (probabilities >= t_low) & (probabilities < t_high)
    bloqueadas = probabilities >= t_high

    taxa_deteccao = costs.get("review_detection_rate", 1.0)
    piso = costs.get("fraud_loss_floor", 0.0)

    # Toda fraude vale ao menos o piso. Uma fraude de card testing custa quase nada na
    # transacao e viabiliza a proxima, que o modelo de custo nao enxerga: sem o piso, a
    # politica nao tem incentivo economico para captura-la (ADR-0024).
    perda_por_fraude = np.maximum(amounts, piso) * costs["fraud_loss_multiplier"]

    perda_fraude = perda_por_fraude[aprovadas & (y_true == 1)].sum()
    custo_revisao = revisadas.sum() * costs["manual_review_cost"]
    custo_bloqueio = (bloqueadas & (y_true == 0)).sum() * costs["false_block_cost"]

    # Fraude encaminhada à revisão só é evitada se o analista de fato a identificar.
    # Sem esta parcela, revisar seria gratuito em termos de risco e bloquear jamais
    # compensaria — a faixa de bloqueio deixaria de existir.
    perda_revisao = (
        perda_por_fraude[revisadas & (y_true == 1)].sum() * (1.0 - taxa_deteccao)
    )

    return {
        "total": float(perda_fraude + custo_revisao + custo_bloqueio + perda_revisao),
        "fraud_loss": float(perda_fraude),
        "review_cost": float(custo_revisao),
        "false_block_cost": float(custo_bloqueio),
        "review_miss_loss": float(perda_revisao),
        "review_fraction": float(revisadas.mean()),
        "block_fraction": float(bloqueadas.mean()),
        "frauds_missed": int((aprovadas & (y_true == 1)).sum()),
    }


def optimize(y_val, probabilities, amounts, config=None) -> tuple[Policy, dict]:
    """Busca os dois limiares na validação, sob restrição de capacidade de revisão."""
    config = config or load_config()
    costs = cfg(config, "policy.costs")
    capacidade = cfg(config, "policy.review_capacity_pct")
    n_pontos = cfg(config, "policy.threshold_grid.n_points")

    y = np.asarray(y_val)
    amounts = np.asarray(amounts)

    # A grade sai dos próprios valores distintos do escore, não de quantis.
    #
    # Quantis parecem razoáveis e falham aqui: a calibração isotônica colapsa dezenas de
    # milhares de escores em poucos platôs — nesta execução, 10 valores distintos — e
    # uma grade por quantil **pula candidatos válidos**. O limiar 0,333333 existia nos
    # escores, não entrava na grade, e era o de menor custo. O otimizador escolhia a
    # segunda melhor opção sem nunca ter visto a primeira.
    #
    # Com poucos valores distintos, avaliá-los todos é trivial. Se a distribuição for
    # rica, cai-se de volta em amostragem por quantil para manter o custo controlado.
    distintos = np.unique(probabilities)
    if len(distintos) <= n_pontos:
        grade = distintos
    else:
        grade = np.unique(np.quantile(distintos, np.linspace(0.0, 1.0, n_pontos)))

    melhor, melhor_custo = None, np.inf
    viaveis = 0
    for t_low in grade:
        for t_high in grade[grade > t_low]:
            resultado = expected_cost(y, probabilities, amounts, t_low, t_high, costs)
            if resultado["review_fraction"] > capacidade:
                continue
            viaveis += 1
            if resultado["total"] < melhor_custo:
                melhor_custo, melhor = resultado["total"], (t_low, t_high, resultado)

    if melhor is None:
        raise RuntimeError(
            f"Nenhum par de limiares respeita a capacidade de revisão de {capacidade:.2%}. "
            "Reveja a restrição ou o modelo de custos."
        )

    t_low, t_high, detalhe = melhor
    politica = Policy(float(t_low), float(t_high))
    logger.info(
        "Política · t_low=%.6f t_high=%.6f · revisão %.3f%% · custo %.2f · fraudes perdidas %d",
        t_low, t_high, 100 * detalhe["review_fraction"], detalhe["total"], detalhe["frauds_missed"],
    )
    return politica, {"thresholds": asdict(politica), "validation": detalhe, "feasible_pairs": viaveis}


def sensitivity(y_val, probabilities, amounts, config=None) -> list[dict]:
    """Como os limiares e o custo se deslocam quando as premissas variam.

    Os custos são arbitrados; a conclusão precisa ser o comportamento da política sob
    variação, não um par específico de números (ADR-0010).
    """
    config = config or load_config()
    base = dict(cfg(config, "policy.costs"))
    pisos = cfg(config, "policy.sensitivity.loss_floors", [base.get("fraud_loss_floor", 0.0)])
    linhas = []
    for piso in pisos:
      for razao in cfg(config, "policy.sensitivity.cost_ratios"):
        for capacidade in cfg(config, "policy.sensitivity.capacity_levels"):
            custos = {**base, "false_block_cost": base["manual_review_cost"] * razao,
                      "fraud_loss_floor": piso}
            ajustado = {**cfg(config, "policy"), "costs": custos, "review_capacity_pct": capacidade}
            try:
                politica, info = optimize(
                    y_val, probabilities, amounts, {**config, "policy": ajustado}
                )
                linhas.append({
                    "loss_floor": piso, "cost_ratio": razao, "capacity": capacidade,
                    "t_low": politica.t_low, "t_high": politica.t_high,
                    "total_cost": info["validation"]["total"],
                    "frauds_missed": info["validation"]["frauds_missed"],
                    "review_fraction": info["validation"]["review_fraction"],
                })
            except RuntimeError:
                linhas.append({"loss_floor": piso, "cost_ratio": razao,
                               "capacity": capacidade, "infeasible": True})
    return linhas


def save_summary(resumo: dict, config=None) -> None:
    config = config or load_config()
    caminho = resolve_path(cfg(config, "paths.reports_dir")) / "policy_summary.json"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(resumo, indent=2, ensure_ascii=False), encoding="utf-8")
