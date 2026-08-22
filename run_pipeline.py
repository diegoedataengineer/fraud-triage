"""Ponto de entrada único do pipeline: da fonte pública ao artefato versionado.

    python run_pipeline.py

Executa ingestão, preparação, treino, calibração, política, avaliação, explicabilidade
e monitoramento, e grava o artefato com o `metadata.json` que amarra código, dados e
experimento (ADR-0016). É este o comando que a esteira executa (Spec 007).
"""

from __future__ import annotations

import sys

from src import __version__, artifacts, evaluate, explainability, figures, policy as policy_mod
from src.ingestion import data_fingerprint
from src.utils import get_logger, load_config, timed
from monitoring import drift_monitor

logger = get_logger("pipeline")


def main() -> int:
    config = load_config()
    logger.info("Pipeline de triagem de fraude · versão %s", __version__)

    with timed(logger, "Pipeline completo"):
        resultado = evaluate.run(save=True)

        avaliacao = resultado["evaluation"]
        adotado = avaliacao["adopted_model"]
        detalhe = avaliacao["models"][adotado]
        modelo = resultado["model"] if adotado == "xgboost" else resultado["baseline"]

        X_test, y_test = resultado["X_test"], resultado["y_test"]
        bruto_test = modelo.predict_proba(X_test)[:, 1]
        limiar = detalhe["operating_point"].get("threshold")

        with timed(logger, "Explicabilidade (SHAP)"):
            explicacao = explainability.run(
                modelo, X_test, y_test, bruto_test, limiar,
                baseline_coefs=resultado["baseline"].coef_[0], config=config,
            )

        with timed(logger, "Monitoramento e drift"):
            top = list(explicacao["global_ranking"]) if explicacao else None
            relatorio_drift = drift_monitor.run(
                resultado["X_train"], X_test, top_features=top, config=config
            )

        from src.policy import Policy

        # O calibrador vem da avaliacao, ajustado FORA-DE-FOLD. Ajusta-lo de novo aqui,
        # sobre a validacao, foi um defeito real e caro: o modelo final treina em
        # treino + validacao (ADR-0026), entao aquele conjunto ja foi visto. Sobre dado
        # visto os escores sao quase separaveis, a isotonica degenera num degrau, e
        # 99,9% das transacoes recebem probabilidade exatamente zero.
        #
        # A consequencia nao era so cosmetica. Os limiares da politica sao calculados
        # sobre a escala fora-de-fold e passavam a ser aplicados sobre outra escala: a
        # faixa de revisao manual, que a politica de tres faixas existe para alimentar,
        # recebia 1 transacao em 42.722. Fraudes bem ranqueadas pelo modelo — escore
        # bruto 0,53, percentil 99,88 — apareciam como probabilidade 0,000000.
        #
        # Um unico ajuste, reaproveitado. Foi a duplicacao que permitiu que medicao e
        # artefato divergissem sem que nada acusasse (ADR-0028).
        calibrador = resultado["calibrators"][adotado]
        limiares = detalhe["policy"]["thresholds"]
        politica = Policy(limiares["t_low"], limiares["t_high"])
        calibrado_test = calibrador.transform(bruto_test)

        # Os custos da política são arbitrados: a conclusão só é confiável se for
        # robusta a eles. Sem esta análise, os limiares seriam um par de números sem
        # defesa (ADR-0010).
        with timed(logger, "Análise de sensibilidade da política"):
            # As mesmas entradas fora-de-fold que definiram a política. Reconstruí-las a
            # partir da validação daria uma sensibilidade sobre dado que o modelo viu.
            import numpy as _np

            mascara = ~_np.isnan(resultado["oof_scores"])
            y_sens = resultado["oof_y"][mascara]
            p_sens = calibrador.transform(
                _np.asarray(resultado["oof_scores"][mascara], dtype=_np.float64)
            )
            amount_sens = _np.concatenate(
                [resultado["amount_train"], resultado["amount_val"]]
            )[mascara]
            linhas = policy_mod.sensitivity(y_sens, p_sens, amount_sens, config)
            viaveis = [linha for linha in linhas if not linha.get("infeasible")]
            logger.info(
                "Sensibilidade: %d de %d combinações viáveis · custo de %.0f a %.0f",
                len(viaveis), len(linhas),
                min(l["total_cost"] for l in viaveis) if viaveis else 0,
                max(l["total_cost"] for l in viaveis) if viaveis else 0,
            )
            policy_mod.save_summary(
                {**detalhe["policy"], "sensitivity": linhas}, config
            )

        with timed(logger, "Geração das figuras"):
            y_np = __import__("numpy").asarray(y_test)
            figures.curva_precision_recall(y_np, bruto_test, config)
            figures.curva_roc(y_np, bruto_test, config)
            if limiar is not None:
                figures.matriz_de_confusao(y_np, bruto_test, limiar, config)
            figures.distribuicao_dos_escores(y_np, calibrado_test, limiares, config)
            figures.diagrama_de_confiabilidade(y_np, bruto_test, calibrado_test, config)
            figures.drift(relatorio_drift["real_drift"], config)
            if explicacao:
                figures.importancia_shap(explicacao["global_ranking"], config)
            figures.sensibilidade(linhas, config)
            figures.sensibilidade_piso(linhas, config)

        with timed(logger, "Gravação do artefato"):
            destino = artifacts.save(
                model=modelo,
                calibrator=calibrador,
                preprocessor=resultado["preprocessor"],
                policy=politica,
                metrics=detalhe["test"],
                extra={
                    "adopted_model": adotado,
                    "hpo": resultado["summary"]["main"].get("n_trials"),
                    "best_params": resultado["summary"]["main"].get("best_params"),
                    "operating_point": detalhe["operating_point"],
                },
                data_sha256=data_fingerprint(),
                config=config,
            )

    minimos_ok = detalhe["meets_rubric_minimums"]
    logger.info("Artefato: %s", destino)
    logger.info(
        "Mínimos da rubrica: %s",
        "atingidos" if minimos_ok else f"NÃO atingidos → {detalhe['rubric_gaps']}",
    )
    # O pipeline conclui mesmo sem os mínimos: quem reprova a build é a porta de
    # qualidade da esteira (src.verify_minimums), que roda em homologação.
    return 0


if __name__ == "__main__":
    sys.exit(main())
