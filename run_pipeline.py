"""Ponto de entrada único do pipeline: da fonte pública ao artefato versionado.

    python run_pipeline.py

Executa ingestão, preparação, treino, calibração, política, avaliação, explicabilidade
e monitoramento, e grava o artefato com o `metadata.json` que amarra código, dados e
experimento (ADR-0016). É este o comando que a esteira executa (Spec 007).
"""

from __future__ import annotations

import sys

from src import __version__, artifacts, evaluate, explainability
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
            drift_monitor.run(resultado["X_train"], X_test, top_features=top, config=config)

        from src.calibration import fit as fit_calibration
        from src.policy import Policy

        calibrador, _ = fit_calibration(modelo, resultado["X_val"], resultado["y_val"], config)
        limiares = detalhe["policy"]["thresholds"]
        politica = Policy(limiares["t_low"], limiares["t_high"])

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
