"""Calibração das probabilidades e medição da qualidade dessa calibração.

Enquanto o modelo apenas ordena transações, a escala do escore não importa — PR-AUC e
ROC-AUC dependem só da ordem. Passa a importar no momento em que o escore vira decisão
com faixas: definir uma faixa de revisão entre dois limiares só faz sentido se os
valores significarem frequência (ADR-0009).
"""

from __future__ import annotations

import json

import numpy as np
from sklearn.calibration import _SigmoidCalibration
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from src.utils import cfg, get_logger, load_config, resolve_path

logger = get_logger("calibration")


def expected_calibration_error(y_true, y_prob, n_bins: int = 10) -> float:
    """ECE em faixas de igual frequência.

    Faixas equifrequentes, e não de largura fixa: com 0,17% de positivos os escores se
    concentram perto de zero, e faixas uniformes deixariam quase todas vazias.
    """
    quantis = np.quantile(y_prob, np.linspace(0, 1, n_bins + 1))
    quantis[0], quantis[-1] = -np.inf, np.inf
    indices = np.digitize(y_prob, quantis[1:-1])
    erro = 0.0
    for faixa in range(n_bins):
        mascara = indices == faixa
        if not mascara.any():
            continue
        erro += mascara.mean() * abs(y_true[mascara].mean() - y_prob[mascara].mean())
    return float(erro)


class Calibrator:
    """Envolve o modelo, mapeando escore bruto em probabilidade calibrada."""

    def __init__(self, method: str, mapper) -> None:
        self.method = method
        self._mapper = mapper

    def transform(self, scores: np.ndarray) -> np.ndarray:
        if self.method == "identity":
            return scores
        saida = self._mapper.predict(scores)
        return np.clip(saida, 0.0, 1.0)


def fit(model, X_val, y_val, config=None) -> tuple[Calibrator, dict]:
    """Ajusta sobre um conjunto que o modelo não viu no treino."""
    config = config or load_config()
    return fit_scores(model.predict_proba(X_val)[:, 1], y_val, config)


def fit_scores(brutos, y_val, config=None) -> tuple[Calibrator, dict]:
    """Ajusta a calibração a partir de escores já calculados.

    Necessário quando o modelo final é treinado em treino + validação: nesse caso não
    resta partição que ele não tenha visto, e a calibração passa a usar as predições
    **fora-de-fold** — cada uma produzida por um modelo que não viu aquela linha. É o
    único conjunto que preserva a condição de honestidade da calibração (ADR-0026).
    """
    config = config or load_config()
    y = np.asarray(y_val)
    # float64 na origem: o XGBoost devolve predict_proba em float32, e a isotonica
    # ajustada sobre float32 emite valores do mesmo plato diferindo em 1 ULP — o
    # bastante para uma verificacao de monotonicidade estrita acusar violacao onde
    # so ha arredondamento. Calibracao e ajuste numerico; nao ha por que fazer em
    # meia precisao.
    brutos = np.asarray(brutos, dtype=np.float64)
    n_bins = cfg(config, "calibration.ece_bins")

    candidatos: dict[str, Calibrator] = {
        "isotonic": Calibrator("isotonic", IsotonicRegression(out_of_bounds="clip").fit(brutos, y)),
        "sigmoid": Calibrator("sigmoid", _SigmoidCalibration().fit(brutos, y)),
    }

    resultados = {
        "raw": {
            "brier": float(brier_score_loss(y, brutos)),
            "ece": expected_calibration_error(y, brutos, n_bins),
        }
    }
    for nome, cal in candidatos.items():
        p = cal.transform(brutos)
        resultados[nome] = {
            "brier": float(brier_score_loss(y, p)),
            "ece": expected_calibration_error(y, p, n_bins),
        }

    # A isotônica é não paramétrica e pode sobreajustar com poucos positivos; por isso
    # comparamos com Platt em vez de assumir isotônica de saída (ADR-0009).
    escolhido = min(candidatos, key=lambda n: resultados[n]["brier"])
    calibrador = candidatos[escolhido]
    calibrados = calibrador.transform(brutos)

    # Invariante real: o mapeamento precisa ser monotônico não decrescente. Verificado
    # de forma exata, ordenando pelo escore bruto.
    #
    # O que NÃO se pode exigir é que PR-AUC e ROC-AUC fiquem idênticas. A isotônica é
    # monotônica mas não estritamente: ela colapsa faixas de escore no mesmo valor,
    # criando empates, e as métricas de ordenação respondem a empates. Exigir
    # igualdade exata reprovaria uma calibração correta — o erro estava no invariante,
    # não na isotônica.
    ordem = np.argsort(brutos, kind="mergesort")
    passos = np.diff(calibrados[ordem])
    # Tolerancia derivada da resolucao do tipo e da escala dos valores, em vez de uma
    # constante arbitraria: o que conta como "zero" depende de ambos.
    tolerancia = 8 * np.finfo(calibrados.dtype).eps * max(1.0, float(np.abs(calibrados).max()))
    if np.any(passos < -tolerancia):
        pior = float(passos.min())
        raise RuntimeError(
            f"Calibração '{escolhido}' não é monotônica não decrescente: "
            f"pior passo {pior:.2e}, tolerância {tolerancia:.2e}."
        )

    tol = cfg(config, "calibration.max_ranking_degradation")
    deltas = {
        "pr_auc": average_precision_score(y, brutos) - average_precision_score(y, calibrados),
        "roc_auc": roc_auc_score(y, brutos) - roc_auc_score(y, calibrados),
    }
    for metrica, queda in deltas.items():
        if queda > tol:
            raise RuntimeError(
                f"Calibração degradou {metrica} em {queda:.2e} (máximo tolerado {tol:.0e}). "
                "Perda dessa magnitude indica empates demais, não calibração."
            )

    # Guarda de RESOLUÇÃO — distinta da guarda de ranking acima, e por um motivo que
    # custou caro descobrir: com base de 0,17%, PR-AUC e ROC-AUC quase não se movem
    # quando a calibração colapsa a massa negativa. Dá para esmagar 99,9% das
    # transações num único valor e a guarda de ranking passar tranquila. Ela foi
    # escrita para pegar exatamente este defeito e é cega a ele.
    #
    # O que se mede aqui é o que de fato quebra: quanta massa vai parar num único
    # valor. Uma isotônica ajustada sobre dado que o modelo já viu — escores quase
    # separáveis — vira degrau, e a política de faixas deixa de ter onde operar,
    # porque não sobra ninguém entre os limiares (ADR-0028).
    _, contagens = np.unique(calibrados, return_counts=True)
    massa_maxima = float(contagens.max() / len(calibrados))
    limite_massa = cfg(config, "calibration.max_single_value_mass")
    if massa_maxima > limite_massa:
        raise RuntimeError(
            f"Calibração '{escolhido}' colapsou {massa_maxima:.2%} da amostra em um "
            f"único valor (máximo tolerado {limite_massa:.0%}), restando "
            f"{len(contagens)} valores distintos. Uma calibração assim não deixa "
            "faixa intermediária onde a política possa operar. A causa usual é "
            "ajustar sobre dado que o modelo já viu, onde os escores são quase "
            "separáveis — verifique se a origem é mesmo fora-de-fold."
        )

    resumo = {
        "selected_method": escolhido,
        "candidates": resultados,
        "ranking_invariance": {k: float(v) for k, v in deltas.items()},
        "resolution": {
            "max_single_value_mass": massa_maxima,
            "n_distinct_values": int(len(contagens)),
        },
        "brier_improvement": resultados["raw"]["brier"] - resultados[escolhido]["brier"],
    }
    logger.info(
        "Calibração · escolhida: %s · Brier %.6f → %.6f · ECE %.4f → %.4f",
        escolhido,
        resultados["raw"]["brier"],
        resultados[escolhido]["brier"],
        resultados["raw"]["ece"],
        resultados[escolhido]["ece"],
    )
    return calibrador, resumo


def save_summary(resumo: dict, config=None) -> None:
    config = config or load_config()
    caminho = resolve_path(cfg(config, "paths.reports_dir")) / "calibration_summary.json"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(resumo, indent=2, ensure_ascii=False), encoding="utf-8")
