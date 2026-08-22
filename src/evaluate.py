"""Avaliação no teste, verificação dos mínimos da rubrica e escolha final do modelo.

O teste é tocado uma única vez, ao final. Escalonador, calibrador e limiares saem do
treino ou da validação — nunca daqui (ADR-0003).
"""

from __future__ import annotations

import json

import numpy as np
from sklearn.metrics import (
    precision_recall_curve,
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from src import calibration, policy
from src.train import run as train_run
from src.utils import cfg, get_logger, load_config, resolve_path, timed

logger = get_logger("evaluate")


def metrics_at(y_true, probabilities, threshold: float) -> dict:
    """Métricas sempre da classe positiva.

    Média ponderada seria dominada pela classe majoritária e passaria de 0,99 sem
    significar nada, com 0,17% de positivos (ADR-0004).
    """
    predito = (probabilities >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, predito, labels=[0, 1]).ravel()
    return {
        "threshold": float(threshold),
        "precision": float(precision_score(y_true, predito, zero_division=0)),
        "recall": float(recall_score(y_true, predito, zero_division=0)),
        "f1": float(f1_score(y_true, predito, zero_division=0)),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


def wilson_lower_bound(successes: np.ndarray, trials: np.ndarray, z: float = 1.96) -> np.ndarray:
    """Limite inferior do intervalo de Wilson para uma proporção.

    Preferido ao intervalo normal porque não degenera quando a proporção se aproxima de
    0 ou 1 nem quando a amostra é pequena — que é exatamente o regime aqui.
    """
    trials = np.maximum(trials, 1)
    p = successes / trials
    z2 = z * z
    centro = p + z2 / (2 * trials)
    raio = z * np.sqrt((p * (1 - p) + z2 / (4 * trials)) / trials)
    return np.clip((centro - raio) / (1 + z2 / trials), 0.0, 1.0)


def select_operating_point(y_val, p_val, minimums: dict, z: float = 1.96) -> dict:
    """Escolhe, na validação, o limiar que atende aos mínimos da rubrica.

    O limiar é exigido a satisfazer os mínimos no **limite inferior de confiança**, não
    no valor pontual. A razão é concreta: com 56 positivos na validação, uma precisão
    medida de 0,81 tem incerteza de vários pontos percentuais, e um limiar escolhido
    colado na fronteira não sobrevive à transferência para o teste — foi o que se
    observou. Exigir a folga via intervalo de confiança embute uma margem proporcional
    à incerteza, em vez de uma margem arbitrada, e é decidido sem olhar o teste.
    """
    y = np.asarray(y_val)
    precisao, recall, limiares = precision_recall_curve(y, p_val)
    precisao, recall = precisao[:-1], recall[:-1]

    total_positivos = int(y.sum())
    # Para cada limiar: quantos foram preditos positivos e quantos acertou.
    verdadeiros = recall * total_positivos
    preditos = np.where(precisao > 0, verdadeiros / np.maximum(precisao, 1e-12), 0.0)

    precisao_lcb = wilson_lower_bound(verdadeiros, preditos, z)
    recall_lcb = wilson_lower_bound(verdadeiros, np.full_like(verdadeiros, total_positivos), z)

    viavel = (precisao_lcb >= minimums["precision"]) & (recall_lcb >= minimums["recall"])
    diagnostico = {
        "n_validation_positives": total_positivos,
        "point_estimate_feasible": bool(
            ((precisao >= minimums["precision"]) & (recall >= minimums["recall"])).any()
        ),
    }

    if not viavel.any():
        return {"feasible": False, **diagnostico}

    # Entre os viáveis, o de maior folga no limite inferior.
    folga = np.minimum(precisao_lcb - minimums["precision"], recall_lcb - minimums["recall"])
    folga[~viavel] = -np.inf
    i = int(np.argmax(folga))
    return {
        "feasible": True,
        "threshold": float(limiares[i]),
        "validation_precision": float(precisao[i]),
        "validation_recall": float(recall[i]),
        "validation_precision_lcb": float(precisao_lcb[i]),
        "validation_recall_lcb": float(recall_lcb[i]),
        "n_feasible_thresholds": int(viavel.sum()),
        **diagnostico,
    }


def evaluate_model(nome, modelo, dados, config) -> dict:
    """Calibra na validação, define a política na validação, mede no teste."""
    X_val, y_val = dados["X_val"], dados["y_val"]
    X_test, y_test = dados["X_test"], dados["y_test"]

    # O modelo final viu a validação, então calibrar nela seria calibrar sobre dado de
    # treino — otimista por construção. Usa-se o fora-de-fold quando disponível.
    escolha = dados.get("threshold_selection")
    if escolha is not None:
        calibrador, resumo_cal = calibration.fit_scores(escolha[1], escolha[0], config)
    else:
        calibrador, resumo_cal = calibration.fit(modelo, X_val, y_val, config)

    # Ranking sobre escore BRUTO. PR-AUC e ROC-AUC medem ordenação, e a isotônica
    # colapsa faixas de escore no mesmo valor: os empates resultantes derrubam essas
    # métricas sem que o modelo tenha piorado. A calibração serve à decisão, não à
    # medição de ordenação.
    bruto_val = modelo.predict_proba(X_val)[:, 1]
    bruto_test = modelo.predict_proba(X_test)[:, 1]

    p_val = calibrador.transform(bruto_val)
    p_test = calibrador.transform(bruto_test)

    # A política é otimizada sobre o fora-de-fold, não sobre a validação.
    #
    # O modelo final treina em treino + validação (ADR-0026), então prever a validação
    # com ele é prever dentro da amostra: os escores ficam quase perfeitos, a política
    # parece não perder fraude alguma e os limiares escolhidos não transferem. É o mesmo
    # cuidado que já se aplicava ao limiar do ponto de operação, agora estendido à
    # política — que também é ajuste, e portanto também precisa de dado não visto.
    if escolha is not None:
        y_pol = escolha[0]
        p_pol = calibrador.transform(np.asarray(escolha[1], dtype=np.float64))
        amounts_pol = dados["amount_cv"]
    else:
        y_pol, p_pol, amounts_pol = y_val, p_val, dados["amount_val"]
    politica, resumo_pol = policy.optimize(y_pol, p_pol, amounts_pol, config)
    dados["_policy_inputs"] = (y_pol, p_pol, amounts_pol)

    y_test_np = np.asarray(y_test)
    y_val_np = np.asarray(y_val)

    # Ponto de operação da rubrica: limiar escolhido na VALIDAÇÃO e aplicado ao teste.
    # É pergunta diferente da política de três faixas — a rubrica avalia um
    # classificador binário; a política descreve a operação. Ambos são reportados.
    minimos = cfg(config, "evaluation.rubric_minimums")
    # Limiar escolhido sobre as predições fora-de-fold quando disponíveis: mais
    # positivos, estimativa mais estável, e nenhuma linha de teste envolvida.
    escolha_y, escolha_p = dados.get("threshold_selection", (y_val_np, bruto_val))
    operacao = select_operating_point(escolha_y, escolha_p, minimos)
    binario = (
        metrics_at(y_test_np, bruto_test, operacao["threshold"])
        if operacao["feasible"]
        else {"threshold": None, "precision": 0.0, "recall": 0.0, "f1": 0.0,
              "confusion_matrix": None}
    )

    faixas = politica.apply(p_test)
    distribuicao = {
        faixa: {
            "n": int((faixas == faixa).sum()),
            "fraction": float((faixas == faixa).mean()),
            "frauds": int(y_test_np[faixas == faixa].sum()),
        }
        for faixa in ("approve", "manual_review", "block")
    }

    resultado = {
        "model": nome,
        "test": {
            "pr_auc": float(average_precision_score(y_test_np, bruto_test)),
            "roc_auc": float(roc_auc_score(y_test_np, bruto_test)),
            "brier": float(brier_score_loss(y_test_np, p_test)),
            "ece": calibration.expected_calibration_error(y_test_np, p_test),
            **binario,
        },
        "operating_point": operacao,
        "calibration": resumo_cal,
        "policy": resumo_pol,
        "band_distribution": distribuicao,
    }

    faltas = {
        nome_m: (resultado["test"][nome_m], piso)
        for nome_m, piso in minimos.items()
        if resultado["test"][nome_m] < piso
    }
    resultado["meets_rubric_minimums"] = not faltas
    resultado["rubric_gaps"] = {k: {"obtido": v[0], "minimo": v[1]} for k, v in faltas.items()}

    logger.info(
        "%-20s · PR-AUC %.4f · ROC-AUC %.4f · P %.4f · R %.4f · F1 %.4f · mínimos: %s",
        nome,
        resultado["test"]["pr_auc"],
        resultado["test"]["roc_auc"],
        resultado["test"]["precision"],
        resultado["test"]["recall"],
        resultado["test"]["f1"],
        "OK" if not faltas else f"FALHA {list(faltas)}",
    )
    return resultado


def run(save: bool = True) -> dict:
    config = load_config()
    treino = train_run(save=save)

    # Valores monetários do fora-de-fold, na mesma ordem de X_cv.
    treino["amount_cv"] = np.concatenate([treino["amount_train"], treino["amount_val"]])

    resultados = {}
    with timed(logger, "Avaliação dos modelos no teste"):
        for nome, modelo in (("logistic_regression", treino["baseline"]), ("xgboost", treino["model"])):
            dados = dict(treino)
            # Ambos os modelos escolhem limiar sobre a mesma base fora-de-fold. Dar
            # 422 positivos a um e 56 ao outro compararia disponibilidade de dados,
            # nao qualidade de modelo.
            oof = treino["oof_scores"] if nome == "xgboost" else treino["oof_baseline"]
            mascara = ~np.isnan(oof)
            dados["threshold_selection"] = (treino["oof_y"][mascara], oof[mascara])
            dados["amount_cv"] = treino["amount_cv"][mascara]
            resultados[nome] = evaluate_model(nome, modelo, dados, config)

    adotado = treino["summary"]["adopted_model"]

    # Viabilidade operacional e pre-condicao, nao desempate: um modelo sem ponto de
    # operacao valido nao consegue operar, por melhor que seja seu PR-AUC. Se o
    # escolhido pelo teste estatistico nao for viavel, adota-se o viavel.
    viaveis = [n for n, r in resultados.items() if r["operating_point"]["feasible"]]
    if adotado not in viaveis and viaveis:
        logger.warning(
            "Modelo %s não tem ponto de operação viável; adotando %s, que tem.",
            adotado, viaveis[0],
        )
        adotado = viaveis[0]
        treino["summary"]["adopted_model"] = adotado
        treino["summary"]["adoption_override"] = "viabilidade do ponto de operação"
    # Se o modelo adotado pelo critério estatístico não atinge os mínimos da rubrica,
    # isso é bloqueio de entrega e precisa aparecer, não ser contornado em silêncio.
    if not resultados[adotado]["meets_rubric_minimums"]:
        alternativas = [n for n, r in resultados.items() if r["meets_rubric_minimums"]]
        logger.warning(
            "Modelo adotado (%s) NÃO atinge os mínimos. Atingem: %s",
            adotado, alternativas or "nenhum",
        )

    treino_resumo = treino["summary"]
    resumo = {
        "adopted_model": adotado,
        "adoption_rationale": {
            chave: treino_resumo[chave]
            for chave in (
                "gain_over_baseline",
                "paired_mean_difference",
                "paired_std_difference",
                "paired_t_statistic",
                "paired_p_value",
                "wilcoxon_p_value",
                "adoption_alpha",
            )
            if chave in treino_resumo
        }
        | {"paired_cv": treino_resumo["cross_validation"]},
        "models": resultados,
        "training": treino_resumo,
        "preprocessing": treino.get("preprocessing_summary"),
    }

    if save:
        caminho = resolve_path(cfg(config, "paths.reports_dir")) / "evaluation_summary.json"
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(json.dumps(resumo, indent=2, ensure_ascii=False), encoding="utf-8")
        calibration.save_summary(resultados[adotado]["calibration"], config)
        policy.save_summary(resultados[adotado]["policy"], config)
        logger.info("Resumo gravado em reports/evaluation_summary.json")

    return {**treino, "evaluation": resumo}


if __name__ == "__main__":
    run()
