"""API de inferência: modelo, calibrador e política de três faixas atrás de HTTP.

Persistência é opcional por configuração: sem `DATABASE_URL` a API responde normalmente
e não grava. Degradar em vez de falhar é deliberado — exigir banco para responder uma
inferência tornaria a avaliação mais frágil sem tornar o modelo melhor (ADR-0018).
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from src import artifacts
from src.utils import cfg, get_logger, load_config

logger = get_logger("api")

app = FastAPI(
    title="Triagem de Fraude",
    description="Política de três faixas sobre probabilidade calibrada.",
    version="1.0.0",
)

ESTADO: dict[str, Any] = {}


class Transaction(BaseModel):
    """Transação no mesmo formato do dataset: Time, V1–V28 e Amount."""

    Time: float = Field(..., ge=0, description="segundos desde a primeira transação")
    Amount: float = Field(..., ge=0, description="valor da transação")
    V: list[float] = Field(..., min_length=28, max_length=28,
                           description="componentes de PCA V1–V28")


class Decision(BaseModel):
    probability: float
    band: str
    action: str
    thresholds: dict[str, float]
    model_version: str


ACOES = {
    "approve": "aprovar automaticamente",
    "manual_review": "encaminhar para revisão manual",
    "block": "bloquear automaticamente",
}


@app.on_event("startup")
def carregar() -> None:
    """Carrega o artefato uma vez, na inicialização — nunca por requisição."""
    config = load_config()
    artefato = artifacts.load(config=config)
    ESTADO.update(artefato)
    ESTADO["config"] = config
    ESTADO["persist"] = bool(os.environ.get("DATABASE_URL"))
    logger.info(
        "Modelo %s carregado de %s · persistência: %s",
        artefato["metadata"]["version"], artefato["path"],
        "ativa" if ESTADO["persist"] else "desativada (sem DATABASE_URL)",
    )


@app.get("/health")
def health() -> dict:
    if not ESTADO:
        raise HTTPException(status_code=503, detail="modelo ainda não carregado")
    meta = ESTADO["metadata"]
    return {
        "status": "ok",
        "model_version": meta["version"],
        "git_sha": meta["git_sha"],
        "metrics": meta["metrics"],
        "persistence": ESTADO["persist"],
    }


@app.post("/predict", response_model=Decision)
def predict(transacao: Transaction) -> Decision:
    if not ESTADO:
        raise HTTPException(status_code=503, detail="modelo ainda não carregado")

    linha = {f"V{i}": v for i, v in enumerate(transacao.V, start=1)}
    linha["Time"] = transacao.Time
    linha["Amount"] = transacao.Amount
    frame = pd.DataFrame([linha])

    # Mesma transformação do treino, reusando o objeto persistido — jamais reajustada.
    X = ESTADO["preprocessor"].transform(frame)
    bruto = ESTADO["model"].predict_proba(X)[:, 1].astype(np.float64)
    probabilidade = float(ESTADO["calibrator"].transform(bruto)[0])

    limiares = ESTADO["policy"]
    if probabilidade >= limiares["t_high"]:
        faixa = "block"
    elif probabilidade >= limiares["t_low"]:
        faixa = "manual_review"
    else:
        faixa = "approve"

    return Decision(
        probability=probabilidade,
        band=faixa,
        action=ACOES[faixa],
        thresholds=limiares,
        model_version=ESTADO["metadata"]["version"],
    )


def main() -> None:
    import uvicorn

    config = load_config()
    uvicorn.run(
        app,
        host=os.environ.get("API_HOST", cfg(config, "serving.host")),
        port=int(os.environ.get("API_PORT", cfg(config, "serving.port"))),
        log_level="info",
    )


if __name__ == "__main__":
    main()
