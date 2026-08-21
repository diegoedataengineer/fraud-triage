"""Utilidades compartilhadas: configuração, sementes, logging e hashing.

Todo módulo do pipeline consome a configuração daqui. Nenhum caminho,
hiperparâmetro ou semente deve aparecer fixo em código (ADR-0013).
"""

from __future__ import annotations

import hashlib
import logging
import os
import random
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import yaml

# Raiz do repositório, derivada da posição deste arquivo. Nunca use caminho
# absoluto: o pipeline precisa rodar igual na máquina de qualquer pessoa,
# dentro do contêiner e na esteira.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"

_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Carrega a configuração central."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(f"Configuração não encontrada: {config_path}")
    with config_path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def cfg(config: dict[str, Any], dotted_key: str, default: Any = ...) -> Any:
    """Lê uma chave aninhada por caminho pontuado: cfg(c, "data.split.train_frac").

    Sem `default`, uma chave ausente levanta erro em vez de devolver None —
    configuração incompleta deve falhar cedo e de forma visível, não silenciosamente
    virar um valor nulo no meio do treino.
    """
    node: Any = config
    for part in dotted_key.split("."):
        if not isinstance(node, dict) or part not in node:
            if default is ...:
                raise KeyError(f"Chave ausente na configuração: '{dotted_key}'")
            return default
        node = node[part]
    return node


def resolve_path(relative: str | Path) -> Path:
    """Converte um caminho da configuração em caminho absoluto sob a raiz do projeto."""
    path = Path(relative)
    return path if path.is_absolute() else PROJECT_ROOT / path


def set_seeds(seed: int) -> None:
    """Fixa as fontes de aleatoriedade do processo.

    Cobre `random`, `numpy` e o hash do Python. Bibliotecas que sorteiam por conta
    própria (Optuna, SHAP, o modelo) recebem a semente explicitamente na chamada —
    depender do estado global é frágil demais para algo que a correção vai reexecutar.
    """
    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)
    np.random.seed(seed)


def get_logger(name: str) -> logging.Logger:
    """Logger com formato único para todas as etapas."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


@contextmanager
def timed(logger: logging.Logger, label: str) -> Iterator[None]:
    """Mede e registra a duração de uma etapa.

    Tempos são reportados no relatório e precisam ser medidos, nunca estimados.
    """
    start = time.perf_counter()
    logger.info("▶ %s", label)
    try:
        yield
    finally:
        logger.info("✔ %s (%.1fs)", label, time.perf_counter() - start)


def sha256_of_file(path: str | Path, chunk_size: int = 1 << 20) -> str:
    """Hash de um arquivo, lido em blocos para não carregar tudo em memória.

    É o que amarra um artefato de modelo aos dados exatos que o treinaram (ADR-0016).
    """
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()
