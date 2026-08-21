"""Comparação de candidatos a modelo principal, exclusivamente por validação cruzada.

**O conjunto de teste não é lido em nenhum ponto deste módulo.** A comparação entre
famílias de modelo, espaços de busca e conjuntos de atributos é feita sobre folds
temporais de treino + validação; o teste só é tocado depois, uma única vez, pelo
vencedor (ADR-0023).
"""

from __future__ import annotations

import json
import os
from typing import Any

import numpy as np
import optuna
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.metrics import average_precision_score
from sklearn.model_selection import TimeSeriesSplit
from xgboost import XGBClassifier

from src.preprocessing import prepare
from src.train import recall_at_precision
from src.utils import cfg, get_logger, load_config, resolve_path, set_seeds, timed

logger = get_logger("model_selection")
optuna.logging.set_verbosity(optuna.logging.WARNING)

INTEIROS = {"max_depth", "min_child_weight", "n_estimators", "num_leaves",
            "min_child_samples", "max_delta_step"}
LOG_SCALE = {"learning_rate", "reg_alpha", "reg_lambda"}


def _build(estimator: str, params: dict, seed: int, config) -> Any:
    if estimator == "xgboost":
        base = dict(cfg(config, "training.main")); base.pop("model", None)
        return XGBClassifier(**base, **params, random_state=seed)
    if estimator == "lightgbm":
        # boost_from_average=False nao e ajuste fino: sem ele o LightGBM fica
        # inutilizavel neste problema. Com 0,18% de positivos ele inicializa o boosting
        # no logit da media (~-6,3), regiao em que os gradientes sao pequenos demais
        # para as arvores recuperarem — PR-AUC de 0,2394 contra 0,7929 com a opcao
        # desligada. Sem isso, incluir o LightGBM na comparacao seria compara-lo
        # quebrado.
        return LGBMClassifier(
            objective="binary", n_jobs=-1, random_state=seed, verbose=-1,
            boost_from_average=False, **params
        )
    raise ValueError(f"Estimador desconhecido: {estimator}")


def _suggest(trial: optuna.Trial, space: dict) -> dict[str, Any]:
    saida: dict[str, Any] = {}
    for nome, (baixo, alto) in space.items():
        if nome in INTEIROS:
            saida[nome] = trial.suggest_int(nome, int(baixo), int(alto))
        else:
            saida[nome] = trial.suggest_float(nome, baixo, alto, log=nome in LOG_SCALE)
    return saida


def evaluate_candidate(candidato: dict, config, n_trials: int) -> dict:
    """Roda a busca de um candidato e devolve seu desempenho em validação cruzada."""
    seed = cfg(config, "project.random_seed")
    piso = cfg(config, "evaluation.rubric_minimums.precision")

    # Cada candidato pode exigir um conjunto de atributos diferente, então o
    # pré-processamento é refeito com a sua própria configuração.
    config_local = json.loads(json.dumps(config))
    config_local["features"]["engineered"]["pca_aggregates"] = candidato["pca_aggregates"]
    dados = prepare(save=False, config=config_local)

    X = pd.concat([dados["X_train"], dados["X_val"]])
    y = pd.concat([dados["y_train"], dados["y_val"]])
    folds = list(TimeSeriesSplit(n_splits=cfg(config, "evaluation.cv.n_splits")).split(X))
    space = cfg(config, candidato["space"])

    def objective(trial: optuna.Trial) -> float:
        params = _suggest(trial, space)
        scores = []
        for treino_idx, teste_idx in folds:
            modelo = _build(candidato["estimator"], params, seed, config)
            modelo.fit(X.iloc[treino_idx], y.iloc[treino_idx])
            proba = modelo.predict_proba(X.iloc[teste_idx])[:, 1]
            scores.append(recall_at_precision(y.iloc[teste_idx], proba, piso))
        trial.set_user_attr("fold_scores", [float(s) for s in scores])
        return float(np.mean(scores))

    study = optuna.create_study(
        direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed)
    )
    with timed(logger, f"{candidato['name']} ({n_trials} tentativas, {X.shape[1]} atributos)"):
        study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    folds_vencedor = study.best_trial.user_attrs.get("fold_scores", [])
    resultado = {
        "name": candidato["name"],
        "estimator": candidato["estimator"],
        "pca_aggregates": candidato["pca_aggregates"],
        "n_features": int(X.shape[1]),
        "cv_recall_at_min_precision": float(study.best_value),
        "cv_folds": folds_vencedor,
        "cv_std": float(np.std(folds_vencedor, ddof=1)) if len(folds_vencedor) > 1 else 0.0,
        "n_folds_feasible": int(sum(1 for s in folds_vencedor if s > 0)),
        "best_params": study.best_params,
        "n_trials": len(study.trials),
    }
    logger.info(
        "%-22s · recall@P≥%.2f = %.4f ± %.4f · folds viáveis %d/%d",
        candidato["name"], piso, resultado["cv_recall_at_min_precision"],
        resultado["cv_std"], resultado["n_folds_feasible"], len(folds_vencedor),
    )
    return resultado


def run(save: bool = True) -> dict:
    config = load_config()
    set_seeds(cfg(config, "project.random_seed"))

    n_trials = int(os.environ.get("SELECTION_TRIALS")
                   or cfg(config, "model_selection.screening_trials"))

    resultados = [
        evaluate_candidate(c, config, n_trials)
        for c in cfg(config, "model_selection.candidates")
    ]
    resultados.sort(key=lambda r: r["cv_recall_at_min_precision"], reverse=True)
    vencedor = resultados[0]

    logger.info("Vencedor da triagem: %s (%.4f)",
                vencedor["name"], vencedor["cv_recall_at_min_precision"])

    resumo = {
        "protocol": "comparação por validação cruzada temporal; o conjunto de teste "
                    "não participa de nenhuma etapa deste módulo",
        "screening_trials": n_trials,
        "winner": vencedor["name"],
        "candidates": resultados,
    }
    if save:
        caminho = resolve_path(cfg(config, "paths.reports_dir")) / "model_selection.json"
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(json.dumps(resumo, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Resumo gravado em reports/model_selection.json")
    return resumo


if __name__ == "__main__":
    run()
