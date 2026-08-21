"""Baseline interpretável e modelo principal com busca de hiperparâmetros.

O baseline não é formalidade: `V1`–`V28` já são projeções lineares descorrelacionadas
(PCA), e um modelo linear opera bem sobre esse tipo de entrada. Se a regressão logística
empatar com o gradient boosting, isso é achado — não fracasso (ADR-0007).
"""

from __future__ import annotations

import json
import os
import warnings
from typing import Any

import numpy as np
import optuna
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, precision_recall_curve
from scipy.stats import ttest_rel, wilcoxon
from sklearn.model_selection import TimeSeriesSplit
from xgboost import XGBClassifier

from src.preprocessing import prepare
from src.utils import cfg, get_logger, load_config, resolve_path, set_seeds, timed

logger = get_logger("train")
optuna.logging.set_verbosity(optuna.logging.WARNING)


def train_baseline(X_train, y_train, config) -> LogisticRegression:
    """Regressão logística ponderada — a referência contra a qual o ganho é medido."""
    model = LogisticRegression(
        class_weight=cfg(config, "training.baseline.class_weight"),
        max_iter=cfg(config, "training.baseline.max_iter"),
        random_state=cfg(config, "project.random_seed"),
    )
    with warnings.catch_warnings(record=True) as avisos:
        warnings.simplefilter("always")
        model.fit(X_train, y_train)
        # Um baseline que não convergiu não é comparação válida.
        if any("converge" in str(a.message).lower() for a in avisos):
            logger.warning("Baseline não convergiu — comparação comprometida.")
    return model


def recall_at_precision(y_true, proba, min_precision: float) -> float:
    """Maior recall alcançável mantendo a precisão acima do piso.

    É a tradução direta do requisito operacional: pegar o máximo de fraude sem que a
    fila de falsos positivos inviabilize a operação. PR-AUC premia a curva inteira,
    inclusive regiões de precisão baixa que nunca seriam usadas — otimizar por ela
    entrega um modelo bom em média e ruim justamente onde ele opera (ADR-0021).
    """
    precisao, recall, _ = precision_recall_curve(y_true, proba)
    viavel = precisao[:-1] >= min_precision
    return float(recall[:-1][viavel].max()) if viavel.any() else 0.0


def _suggest(trial: optuna.Trial, space: dict) -> dict[str, Any]:
    """Traduz o espaço declarado em config para sugestões do Optuna."""
    inteiros = {"max_depth", "min_child_weight", "n_estimators"}
    log_scale = {"learning_rate", "reg_alpha", "reg_lambda"}
    params: dict[str, Any] = {}
    for nome, (baixo, alto) in space.items():
        if nome in inteiros:
            params[nome] = trial.suggest_int(nome, int(baixo), int(alto))
        else:
            params[nome] = trial.suggest_float(nome, baixo, alto, log=nome in log_scale)
    return params


def train_main(X_train, y_train, X_val, y_val, config) -> tuple[XGBClassifier, dict]:
    """XGBoost com busca bayesiana, otimizando PR-AUC na validação (ADR-0004)."""
    seed = cfg(config, "project.random_seed")
    base = dict(cfg(config, "training.main"))
    base.pop("model", None)
    space = cfg(config, "training.hpo.search_space")
    early = cfg(config, "training.hpo.early_stopping_rounds")

    # Permite orçamento reduzido na esteira sem alterar código (Spec 007).
    n_trials = int(os.environ.get("HPO_N_TRIALS") or cfg(config, "training.hpo.n_trials"))

    # O objetivo e PR-AUC media em validacao cruzada temporal, nao no split unico de
    # validacao. Com 56 positivos na validacao, otimizar 50 tentativas contra aquele
    # unico conjunto sobreajusta: uma versao anterior atingiu 0,8811 na validacao e
    # caiu para 0,6806 no teste. Media entre folds e um alvo muito mais estavel.
    X_hpo = pd.concat([X_train, X_val])
    y_hpo = pd.concat([y_train, y_val])
    splitter = TimeSeriesSplit(n_splits=cfg(config, "evaluation.cv.n_splits"))
    folds = list(splitter.split(X_hpo))

    piso_precisao = cfg(config, "evaluation.rubric_minimums.precision")

    def objective(trial: optuna.Trial) -> float:
        params = _suggest(trial, space)
        scores, pr_aucs = [], []
        for treino_idx, teste_idx in folds:
            model = XGBClassifier(**base, **params, random_state=seed)
            model.fit(X_hpo.iloc[treino_idx], y_hpo.iloc[treino_idx], verbose=False)
            proba = model.predict_proba(X_hpo.iloc[teste_idx])[:, 1]
            y_fold = y_hpo.iloc[teste_idx]
            scores.append(recall_at_precision(y_fold, proba, piso_precisao))
            pr_aucs.append(average_precision_score(y_fold, proba))
        trial.set_user_attr("fold_scores", [float(s) for s in scores])
        trial.set_user_attr("fold_pr_auc", [float(s) for s in pr_aucs])
        # PR-AUC entra como desempate: entre configuracoes com o mesmo recall na
        # regiao util, prefere-se a de curva melhor no restante.
        return float(np.mean(scores)) + 1e-4 * float(np.mean(pr_aucs))

    study = optuna.create_study(
        direction=cfg(config, "training.hpo.direction"),
        sampler=optuna.samplers.TPESampler(seed=seed),
    )
    with timed(logger, f"Busca de hiperparâmetros ({n_trials} tentativas)"):
        study.optimize(
            objective,
            n_trials=n_trials,
            timeout=cfg(config, "training.hpo.timeout_seconds"),
            show_progress_bar=False,
        )

    logger.info("Melhor recall@precisão≥%.2f (média entre folds): %.4f", piso_precisao, study.best_value)

    # Modelo final treinado no treino, com a validacao reservada para calibracao e
    # limiares — que nao podem ser estimados sobre dados que o modelo ja viu.
    best = XGBClassifier(
        **base, **study.best_params, random_state=seed, early_stopping_rounds=early
    )
    best.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)

    # Predições fora-de-fold: cada linha prevista por um modelo que não a viu no
    # treino. Reunidas, dão ~422 positivos para escolher o limiar, contra os 56 da
    # validação isolada — a diferença entre um limiar estável e um que não transfere.
    oof = np.full(len(X_hpo), np.nan)
    for treino_idx, teste_idx in folds:
        m = XGBClassifier(**base, **study.best_params, random_state=seed)
        m.fit(X_hpo.iloc[treino_idx], y_hpo.iloc[treino_idx], verbose=False)
        oof[teste_idx] = m.predict_proba(X_hpo.iloc[teste_idx])[:, 1]

    val_pr = average_precision_score(y_val, best.predict_proba(X_val)[:, 1])
    info = {
        "oof_scores": oof,
        "oof_y": y_hpo.to_numpy(),
        "n_trials": len(study.trials),
        "best_params": study.best_params,
        "best_cv_pr_auc": float(study.best_value),
        "best_cv_folds": study.best_trial.user_attrs.get("fold_scores", []),
        "best_val_pr_auc": float(val_pr),
        "best_iteration": int(getattr(best, "best_iteration", 0) or 0),
    }
    return best, info


def cross_validate(model_factory, X, y, config) -> dict[str, float]:
    """Validação cruzada temporal — nunca embaralhada (ADR-0003).

    O desvio entre folds define o que conta como ganho real na adoção do modelo:
    diferença menor que a variância do próprio experimento é ruído.
    """
    splitter = TimeSeriesSplit(n_splits=cfg(config, "evaluation.cv.n_splits"))
    scores = []
    for treino_idx, teste_idx in splitter.split(X):
        modelo = model_factory()
        modelo.fit(X.iloc[treino_idx], y.iloc[treino_idx])
        proba = modelo.predict_proba(X.iloc[teste_idx])[:, 1]
        scores.append(average_precision_score(y.iloc[teste_idx], proba))
    return {
        "mean": float(np.mean(scores)),
        "std": float(np.std(scores)),
        "folds": [float(s) for s in scores],
    }


def run(save: bool = True) -> dict[str, Any]:
    config = load_config()
    set_seeds(cfg(config, "project.random_seed"))

    dados = prepare(save=save)
    X_train, y_train = dados["X_train"], dados["y_train"]
    X_val, y_val = dados["X_val"], dados["y_val"]

    with timed(logger, "Baseline (regressão logística)"):
        baseline = train_baseline(X_train, y_train, config)
    baseline_val = average_precision_score(y_val, baseline.predict_proba(X_val)[:, 1])
    logger.info("Baseline · PR-AUC na validação: %.4f", baseline_val)

    modelo, info = train_main(X_train, y_train, X_val, y_val, config)
    oof_scores, oof_y = info.pop("oof_scores"), info.pop("oof_y")

    treino_pr = average_precision_score(y_train, modelo.predict_proba(X_train)[:, 1])
    val_pr = info["best_val_pr_auc"]
    gap = treino_pr - val_pr
    logger.info(
        "Gap de generalização · treino %.4f − validação %.4f = %.4f", treino_pr, val_pr, gap
    )

    X_cv = pd.concat([X_train, X_val])
    y_cv = pd.concat([y_train, y_val])
    seed = cfg(config, "project.random_seed")

    def _oof(fabrica) -> np.ndarray:
        """Predições fora-de-fold: cada linha prevista por um modelo que não a viu."""
        saida = np.full(len(X_cv), np.nan)
        for treino_idx, teste_idx in TimeSeriesSplit(
            n_splits=cfg(config, "evaluation.cv.n_splits")
        ).split(X_cv):
            m = fabrica()
            m.fit(X_cv.iloc[treino_idx], y_cv.iloc[treino_idx])
            saida[teste_idx] = m.predict_proba(X_cv.iloc[teste_idx])[:, 1]
        return saida

    with timed(logger, "Validação cruzada temporal — baseline"):
        cv = cross_validate(
            lambda: LogisticRegression(
                class_weight="balanced",
                max_iter=cfg(config, "training.baseline.max_iter"),
                random_state=seed,
            ),
            X_cv, y_cv, config,
        )
    logger.info("CV temporal · baseline: PR-AUC %.4f ± %.4f", cv["mean"], cv["std"])
    oof_baseline = _oof(lambda: LogisticRegression(
        class_weight="balanced",
        max_iter=cfg(config, "training.baseline.max_iter"),
        random_state=seed,
    ))

    # CV também no modelo principal: comparar um valor de validação contra o desvio
    # entre folds do baseline mediria coisas diferentes. Pareado por fold, a
    # comparação é honesta — e é o que o relatório precisa discutir.
    base_params = dict(cfg(config, "training.main"))
    base_params.pop("model", None)
    with timed(logger, "Validação cruzada temporal — modelo principal"):
        cv_main = cross_validate(
            lambda: XGBClassifier(**base_params, **info["best_params"], random_state=seed),
            X_cv, y_cv, config,
        )
    logger.info("CV temporal · XGBoost:  PR-AUC %.4f ± %.4f", cv_main["mean"], cv_main["std"])

    diferencas = [m - b for m, b in zip(cv_main["folds"], cv["folds"])]
    vitorias = sum(1 for d in diferencas if d > 0)
    logger.info(
        "Pareado por fold · XGBoost vence em %d de %d · diferença média %+.4f",
        vitorias, len(diferencas), float(np.mean(diferencas)),
    )

    # Critério pareado por fold. A formulação original comparava a diferença medida em
    # um único split de validação contra o desvio entre folds do baseline — duas
    # grandezas incomensuráveis: uma é diferença, a outra é dispersão de nível. O teste
    # correto para comparar dois modelos sob validação cruzada é sobre as diferenças
    # pareadas (ADR-0020).
    media_dif = float(np.mean(diferencas))
    desvio_dif = float(np.std(diferencas, ddof=1))
    n = len(diferencas)

    # Comparar a média das diferenças com o desvio-padrão delas responde "o efeito é
    # maior que a dispersão individual?" — pergunta de tamanho de efeito, não de
    # significância. O teste correto para o mesmo modelo avaliado nos mesmos folds é o
    # t pareado, cujo denominador é o erro-padrão da média. Pela formulação anterior,
    # um modelo que vence em 5 de 5 folds era rejeitado por 0,0006 (ADR-0020).
    t_stat, p_valor = ttest_rel(cv_main["folds"], cv["folds"], alternative="greater")
    # Wilcoxon como verificação sem suposição de normalidade; com n=5 o menor
    # p-valor alcançável é 0,03125, então serve de apoio, não de árbitro.
    try:
        _, p_wilcoxon = wilcoxon(
            cv_main["folds"], cv["folds"], alternative="greater", zero_method="zsplit"
        )
    except ValueError:
        p_wilcoxon = float("nan")

    alfa = cfg(config, "evaluation.adoption_alpha", 0.05)
    adotado = "xgboost" if p_valor < alfa else "logistic_regression"
    ganho = val_pr - baseline_val
    logger.info(
        "Critério pareado · média %+.4f ± %.4f (n=%d) · t=%.3f p=%.4f "
        "(Wilcoxon p=%.4f) → adotado: %s",
        media_dif, desvio_dif / np.sqrt(n), n, t_stat, p_valor, p_wilcoxon, adotado,
    )

    resumo = {
        "baseline": {"val_pr_auc": float(baseline_val)},
        "main": {
            **info,
            "train_pr_auc": float(treino_pr),
            "generalization_gap": float(gap),
        },
        "cross_validation": {
            "baseline": cv,
            "main": cv_main,
            "paired_differences": [float(d) for d in diferencas],
            "main_wins_folds": f"{vitorias}/{len(diferencas)}",
            "mean_difference": float(np.mean(diferencas)),
        },
        "gain_over_baseline": float(ganho),
        "paired_mean_difference": media_dif,
        "paired_std_difference": desvio_dif,
        "paired_t_statistic": float(t_stat),
        "paired_p_value": float(p_valor),
        "wilcoxon_p_value": float(p_wilcoxon),
        "adoption_alpha": alfa,
        "adopted_model": adotado,
    }

    if save:
        caminho = resolve_path(cfg(config, "paths.reports_dir")) / "training_summary.json"
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(json.dumps(resumo, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Resumo gravado em reports/training_summary.json")

    # `dados` tambem traz uma chave "summary" (a do pre-processamento). Desempacotar
    # por ultimo sobrescreveria o resumo do treino em silencio — por isso vem primeiro.
    return {
        **dados,
        "preprocessing_summary": dados["summary"],
        "baseline": baseline,
        "model": modelo,
        "summary": resumo,
        "oof_scores": oof_scores,
        "oof_baseline": oof_baseline,
        "oof_y": oof_y,
        "X_hpo": X_cv,
    }


if __name__ == "__main__":
    run()
