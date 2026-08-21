"""Persistência do artefato de modelo e do metadata que o identifica.

O `metadata.json` é o que transforma um número de versão em rastro: ele amarra as três
dimensões de versionamento — código (`git_sha`), dados (`data.sha256`) e experimento
(parâmetros e métricas). É o identificador que torna "reproduzir o modelo do mês passado"
uma operação trivial em vez de impossível (ADR-0016).
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import joblib

from src import __version__
from src.utils import cfg, get_logger, load_config, resolve_path

logger = get_logger("artifacts")


def git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            cwd=resolve_path("."), timeout=10, check=True,
        ).stdout.strip()
    except Exception:
        # Em contêiner sem .git isso é esperado; o valor precisa aparecer como
        # desconhecido em vez de quebrar a gravação do artefato.
        return "unknown"


def installed_versions() -> dict[str, str]:
    """Versões efetivamente instaladas — não as pedidas no requirements."""
    from importlib.metadata import PackageNotFoundError, version
    pacotes = ("numpy", "pandas", "scikit-learn", "xgboost", "lightgbm", "shap", "optuna")
    saida = {}
    for nome in pacotes:
        try:
            saida[nome] = version(nome)
        except PackageNotFoundError:
            continue
    return saida


def save(model, calibrator, preprocessor, policy, metrics: dict, extra: dict,
         data_sha256: str, config=None, version: str | None = None) -> Path:
    config = config or load_config()
    versao = version or __version__
    destino = resolve_path(cfg(config, "versioning.registry_dir")) / versao
    destino.mkdir(parents=True, exist_ok=True)

    nomes = cfg(config, "versioning.artifacts")
    joblib.dump(model, destino / nomes["model"])
    joblib.dump(
        {"calibrator": calibrator, "preprocessor": preprocessor},
        destino / nomes["preprocessor"],
    )
    (destino / nomes["policy"]).write_text(
        json.dumps({"t_low": policy.t_low, "t_high": policy.t_high}, indent=2),
        encoding="utf-8",
    )

    import platform

    metadata = {
        "version": versao,
        "git_sha": git_sha(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data": {
            "source": f"openml:{cfg(config, 'data.openml_data_id')}",
            "sha256": data_sha256,
            "n_rows": cfg(config, "data.expected.n_rows"),
        },
        "training": {
            "seed": cfg(config, "project.random_seed"),
            **extra,
        },
        "metrics": metrics,
        "policy": {"t_low": policy.t_low, "t_high": policy.t_high},
        "environment": {
            "python": platform.python_version(),
            "dependencies": installed_versions(),
        },
    }

    obrigatorios = cfg(config, "versioning.metadata_required_fields")
    faltando = [
        chave for chave in obrigatorios
        if _profundo(metadata, chave) in (None, "", {})
    ]
    if faltando:
        raise RuntimeError(f"metadata.json incompleto — campos ausentes: {faltando}")

    (destino / nomes["metadata"]).write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info("Artefato gravado em %s", destino.relative_to(resolve_path(".")))
    return destino


def _profundo(dados: dict, caminho: str):
    no = dados
    for parte in caminho.split("."):
        if not isinstance(no, dict) or parte not in no:
            return None
        no = no[parte]
    return no


def load(version: str | None = None, config=None) -> dict:
    """Carrega o artefato de uma versão, ou a mais recente disponível."""
    config = config or load_config()
    raiz = resolve_path(cfg(config, "versioning.registry_dir"))
    if version:
        destino = raiz / version
    else:
        candidatos = sorted(p for p in raiz.iterdir() if p.is_dir())
        if not candidatos:
            raise FileNotFoundError(f"Nenhum artefato em {raiz}. Rode run_pipeline.py.")
        destino = candidatos[-1]

    nomes = cfg(config, "versioning.artifacts")
    pacote = joblib.load(destino / nomes["preprocessor"])
    return {
        "path": destino,
        "model": joblib.load(destino / nomes["model"]),
        "calibrator": pacote["calibrator"],
        "preprocessor": pacote["preprocessor"],
        "policy": json.loads((destino / nomes["policy"]).read_text(encoding="utf-8")),
        "metadata": json.loads((destino / nomes["metadata"]).read_text(encoding="utf-8")),
    }
