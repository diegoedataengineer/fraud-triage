"""Ingestão do dataset bruto a partir do OpenML, com validação da fonte.

O download é feito do ARFF bruto e não via `fetch_openml`: o OpenML marca a coluna
`Time` como atributo ignorado, e o scikit-learn respeita essa marcação mesmo ao
devolver o frame completo — a coluna simplesmente não aparece, sem erro. Como o
particionamento cronológico depende inteiramente de `Time`, usar a API padrão
inviabilizaria a decisão metodológica central do projeto (ADR-0002).
"""

from __future__ import annotations

import io
import time
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd

from src.utils import (
    cfg,
    get_logger,
    load_config,
    resolve_path,
    sha256_of_file,
    timed,
)

logger = get_logger("ingestion")

_USER_AGENT = "fraud-triage/ingestion"


class SourceValidationError(RuntimeError):
    """A fonte não corresponde ao que o projeto espera.

    Erro, e não aviso, de propósito: dado divergente não pode seguir adiante em
    silêncio e virar um modelo treinado sobre outra coisa.
    """


def _download(url: str, timeout: int, retries: int) -> bytes:
    """Baixa o ARFF, com novas tentativas para falha transitória de rede."""
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read()
            logger.info("Download concluído: %.1f MB", len(payload) / 1e6)
            return payload
        except (urllib.error.URLError, TimeoutError) as error:
            last_error = error
            logger.warning("Tentativa %d/%d falhou: %s", attempt, retries, error)
            if attempt < retries:
                time.sleep(2**attempt)
    raise SourceValidationError(
        f"Não foi possível baixar a fonte após {retries} tentativas: {last_error}"
    )


def parse_arff(payload: bytes) -> pd.DataFrame:
    """Converte o ARFF em DataFrame.

    O formato é simples o bastante para não justificar uma dependência: os nomes de
    coluna saem das linhas `@attribute` e o corpo, após `@data`, é CSV sem cabeçalho.
    """
    text = payload.decode("utf-8", errors="replace")
    lines = text.splitlines()

    columns = [
        line.split()[1].strip("'\"")
        for line in lines
        if line.lower().startswith("@attribute")
    ]
    if not columns:
        raise SourceValidationError("Nenhuma linha @attribute encontrada no ARFF.")

    try:
        data_start = next(
            index for index, line in enumerate(lines) if line.strip().lower() == "@data"
        )
    except StopIteration as error:
        raise SourceValidationError("Marcador @data ausente no ARFF.") from error

    frame = pd.read_csv(
        io.StringIO("\n".join(lines[data_start + 1 :])),
        header=None,
        names=columns,
    )
    # O ARFF cita valores nominais; o alvo chega como "'0'"/"'1'".
    frame["Class"] = frame["Class"].astype(str).str.strip("'\"").astype(int)
    return frame


def validate(frame: pd.DataFrame, expected: dict) -> None:
    """Confere a fonte contra os valores verificados e registrados na configuração."""
    problems: list[str] = []

    if len(frame) != expected["n_rows"]:
        problems.append(f"linhas: {len(frame)} ≠ {expected['n_rows']}")

    if frame.shape[1] != expected["n_cols"]:
        problems.append(f"colunas: {frame.shape[1]} ≠ {expected['n_cols']}")

    required = {"Time", "Amount", "Class", *(f"V{i}" for i in range(1, 29))}
    missing = required - set(frame.columns)
    if missing:
        problems.append(f"colunas ausentes: {sorted(missing)}")

    nulls = int(frame.isna().sum().sum())
    if nulls:
        problems.append(f"valores nulos: {nulls}")

    classes = set(frame["Class"].unique())
    if not classes <= {0, 1}:
        problems.append(f"valores de Class fora de {{0,1}}: {sorted(classes)}")

    positives = int(frame["Class"].sum())
    if positives != expected["n_positives"]:
        problems.append(f"positivos: {positives} ≠ {expected['n_positives']}")

    rate = frame["Class"].mean()
    tolerance = expected["positive_rate_tolerance"]
    if abs(rate - expected["positive_rate"]) > tolerance:
        problems.append(f"taxa de positivos: {rate:.6f} ≠ {expected['positive_rate']}")

    # Sem ordenação cronológica não há como fazer o split temporal (ADR-0003).
    if not frame["Time"].is_monotonic_increasing:
        problems.append("Time não é monotonicamente crescente")

    span = int(frame["Time"].max() - frame["Time"].min())
    if span != expected["time_span_seconds"]:
        problems.append(f"amplitude de Time: {span}s ≠ {expected['time_span_seconds']}s")

    if frame["Amount"].min() < 0:
        problems.append(f"Amount negativo: mínimo {frame['Amount'].min()}")

    if problems:
        raise SourceValidationError(
            "A fonte divergiu do esperado:\n  - " + "\n  - ".join(problems)
        )

    logger.info(
        "Fonte validada: %d linhas × %d colunas · %d fraudes (%.4f%%) · %.1f h",
        len(frame),
        frame.shape[1],
        positives,
        100 * rate,
        span / 3600,
    )


def load_raw(force_download: bool = False) -> pd.DataFrame:
    """Devolve o dataset bruto validado, usando cache em Parquet quando disponível."""
    config = load_config()
    cache_path = resolve_path(cfg(config, "data.raw_cache_path"))
    expected = cfg(config, "data.expected")

    if cache_path.exists() and not force_download:
        with timed(logger, f"Carregando cache {cache_path.name}"):
            frame = pd.read_parquet(cache_path)
        validate(frame, expected)
        return frame

    url = cfg(config, "data.arff_url")
    with timed(logger, f"Baixando fonte ({url})"):
        payload = _download(
            url,
            timeout=cfg(config, "data.download_timeout_seconds"),
            retries=cfg(config, "data.download_retries"),
        )

    with timed(logger, "Interpretando ARFF"):
        frame = parse_arff(payload)

    validate(frame, expected)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with timed(logger, f"Gravando cache {cache_path.name}"):
        frame.to_parquet(cache_path, index=False)

    return frame


def data_fingerprint(path: str | Path | None = None) -> str:
    """Hash do cache, gravado no metadata do modelo para amarrá-lo aos dados (ADR-0016)."""
    config = load_config()
    target = resolve_path(path or cfg(config, "data.raw_cache_path"))
    if not target.exists():
        raise FileNotFoundError(f"Cache inexistente: {target}. Rode a ingestão antes.")
    return sha256_of_file(target)


if __name__ == "__main__":
    dataset = load_raw()
    print(dataset.head())
    print(f"\nsha256 do cache: {data_fingerprint()}")
