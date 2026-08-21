"""Explicabilidade por valores de Shapley, em três níveis de leitura.

Uma limitação precisa ser dita de saída, e o relatório a repete: `V1`–`V28` são
componentes de PCA anonimizadas. **Nenhuma técnica de explicabilidade pode dizer o que
`V14` significa em termos de negócio** — essa informação foi destruída na anonimização
do dataset. Atribuir sentido semântico a essas variáveis seria fabricação. Apenas
`Amount` e `Hour` são diretamente interpretáveis (ADR-0011).
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import shap

from src.utils import cfg, get_logger, load_config, resolve_path

logger = get_logger("explainability")


def stratified_sample(X: pd.DataFrame, y, size: int, seed: int) -> np.ndarray:
    """Amostra preservando a proporção de classes e mantendo **todos** os positivos.

    Positivos são escassos e são o objeto de interesse: descartá-los por sorteio
    tornaria a explicação cega justamente ao fenômeno que se quer explicar.
    """
    y = np.asarray(y)
    positivos = np.flatnonzero(y == 1)
    negativos = np.flatnonzero(y == 0)
    rng = np.random.default_rng(seed)
    n_neg = max(0, min(len(negativos), size - len(positivos)))
    return np.concatenate([positivos, rng.choice(negativos, size=n_neg, replace=False)])


def _casos_locais(y_true, probabilities, threshold: float) -> dict[str, int | None]:
    """Um verdadeiro positivo, um falso positivo e um falso negativo, escolhidos
    deterministicamente pelo escore.

    Os dois últimos são os mais informativos e os que costumam ser omitidos: mostram
    onde o modelo erra, e por quê.
    """
    y = np.asarray(y_true)
    predito = probabilities >= threshold
    def extremo(mascara, maior: bool):
        idx = np.flatnonzero(mascara)
        if idx.size == 0:
            return None
        return int(idx[np.argmax(probabilities[idx])] if maior
                   else idx[np.argmin(probabilities[idx])])
    return {
        "true_positive": extremo(predito & (y == 1), maior=True),
        "false_positive": extremo(predito & (y == 0), maior=True),
        "false_negative": extremo(~predito & (y == 1), maior=False),
    }


def run(model, X_test, y_test, probabilities, threshold, baseline_coefs=None,
        config=None, save: bool = True) -> dict:
    config = config or load_config()
    seed = cfg(config, "project.random_seed")
    tamanho = cfg(config, "explainability.sample_size")
    top_n = cfg(config, "explainability.top_features")

    indices = stratified_sample(X_test, y_test, tamanho, seed)
    amostra = X_test.iloc[indices]
    logger.info(
        "Amostra do SHAP: %d linhas (%d fraudes, todas incluídas)",
        len(amostra), int(np.asarray(y_test)[indices].sum()),
    )

    # TreeExplainer é exato para modelos de árvore, sem a aproximação por amostragem
    # do explicador genérico; para o baseline linear, LinearExplainer cumpre o papel
    # equivalente e também é exato.
    if hasattr(model, "coef_"):
        explainer = shap.LinearExplainer(model, amostra)
    else:
        explainer = shap.TreeExplainer(model)
    valores = explainer.shap_values(amostra)
    if isinstance(valores, list):
        valores = valores[1]

    importancia = np.abs(valores).mean(axis=0)
    ranking_shap = (
        pd.Series(importancia, index=X_test.columns).sort_values(ascending=False)
    )

    # Verificação cruzada com fontes independentes: convergência reforça a leitura,
    # divergência é discutida em vez de escondida.
    cruzada = {"shap": ranking_shap.head(top_n).round(6).to_dict()}
    if hasattr(model, "feature_importances_"):
        cruzada["model_gain"] = (
            pd.Series(model.feature_importances_, index=X_test.columns)
            .sort_values(ascending=False).head(top_n).round(6).to_dict()
        )
    if baseline_coefs is not None:
        cruzada["baseline_coefficients"] = (
            pd.Series(np.abs(baseline_coefs), index=X_test.columns)
            .sort_values(ascending=False).head(top_n).round(6).to_dict()
        )

    casos = _casos_locais(y_test, probabilities, threshold)
    explicacoes_locais = {}
    for nome, posicao_global in casos.items():
        if posicao_global is None:
            explicacoes_locais[nome] = None
            continue
        local = np.flatnonzero(indices == posicao_global)
        if local.size == 0:
            explicacoes_locais[nome] = {"observacao": "caso fora da amostra do SHAP"}
            continue
        i = int(local[0])
        contribuicoes = pd.Series(valores[i], index=X_test.columns)
        maiores = contribuicoes.reindex(contribuicoes.abs().sort_values(ascending=False).index)
        explicacoes_locais[nome] = {
            "score": float(probabilities[posicao_global]),
            "top_factors": maiores.head(8).round(6).to_dict(),
        }

    interpretaveis = [c for c in X_test.columns if not c.startswith("V")]
    resumo = {
        "sample_size": int(len(amostra)),
        "global_ranking": ranking_shap.head(top_n).round(6).to_dict(),
        "cross_check": cruzada,
        "local_cases": explicacoes_locais,
        "interpretability_limit": (
            "V1–V28 são componentes de PCA anonimizadas: não é possível atribuir "
            "significado de negócio a elas. A leitura semântica se restringe a "
            f"{interpretaveis}."
        ),
    }

    if save:
        caminho = resolve_path(cfg(config, "paths.reports_dir")) / "explainability_summary.json"
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(json.dumps(resumo, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Resumo gravado em reports/explainability_summary.json")

    logger.info("Top-5 SHAP: %s", ", ".join(ranking_shap.head(5).index))
    return resumo
