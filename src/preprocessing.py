"""Particionamento cronológico, engenharia de atributos e escalonamento.

A ordem das operações aqui não é estilística: é o que impede vazamento. Particiona-se
primeiro, e só então qualquer estatística é estimada — sempre sobre o treino, nunca
sobre validação ou teste (ADR-0003).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.preprocessing import RobustScaler

from src.ingestion import load_raw
from src.utils import cfg, get_logger, load_config, resolve_path, timed

logger = get_logger("preprocessing")


class LeakageError(RuntimeError):
    """Uma invariante de vazamento foi violada."""


@dataclass
class Preprocessor:
    """Transformações ajustadas no treino e apenas aplicadas às demais partições.

    Persistido junto ao modelo: em produção, a mesma transformação precisa ser
    reaplicada exatamente, e reajustá-la sobre dados novos mudaria silenciosamente o
    significado das features.
    """

    amount_col: str
    scaling_columns: list[str]
    pca_aggregates: bool = False
    hour_stats: dict[int, tuple[float, float]] = field(default_factory=dict)
    global_amount_mean: float = 0.0
    global_amount_std: float = 1.0
    scaler: RobustScaler | None = None
    feature_names: list[str] = field(default_factory=list)

    @property
    def _v_cols(self) -> list[str]:
        return [f"V{i}" for i in range(1, 29)]

    @property
    def _hour_means(self) -> pd.Series:
        return pd.Series({h: v[0] for h, v in self.hour_stats.items()}, dtype="float64")

    @property
    def _hour_stds(self) -> pd.Series:
        return pd.Series({h: v[1] for h, v in self.hour_stats.items()}, dtype="float64")

    def engineer(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Deriva os atributos. Usa apenas estatísticas já fixadas no ajuste."""
        out = frame.copy()
        amount = out[self.amount_col]

        # Amount é fortemente assimétrico (mediana 22, máximo 25.691).
        out["Amount_log"] = np.log1p(amount)

        # Hora do dia captura sazonalidade intradiária. Time bruto fica de fora das
        # features: ele é eixo de particionamento, e mantê-lo ensinaria o modelo o
        # intervalo específico das 48h observadas, que não generaliza.
        hour = (out["Time"] / 3600).mod(24).astype(int)
        out["Hour"] = hour

        # Um valor atípico *para aquele horário* diz mais que um valor alto absoluto.
        # Lookup vetorizado por Series: `dict.get(h, default)` dentro de um lambda
        # avalia o default a cada linha, o que transformava esta etapa em minutos.
        means = hour.map(self._hour_means).fillna(self.global_amount_mean)
        stds = (
            hour.map(self._hour_stds)
            .fillna(self.global_amount_std)
            .replace(0, self.global_amount_std)
        )
        out["Amount_zscore_by_hour"] = (amount - means) / stds

        if self.pca_aggregates:
            # As componentes V1-V28 sao anonimas, entao nao ha interacao semantica a
            # construir. O que existe e estrutura geometrica: fraude tende a cair longe
            # do centro do espaco latente e a puxar poucas componentes para valores
            # extremos. Estes tres agregados capturam isso sem inventar significado.
            v = out[self._v_cols].to_numpy()
            out["V_l2_norm"] = np.sqrt((v ** 2).sum(axis=1))       # distancia da origem
            out["V_max_abs"] = np.abs(v).max(axis=1)               # componente mais extrema
            out["V_outlier_count"] = (np.abs(v) > 3.0).sum(axis=1) # quantas fora de 3 sigma
        return out

    def fit(self, train: pd.DataFrame) -> "Preprocessor":
        amount = train[self.amount_col]
        hour = (train["Time"] / 3600).mod(24).astype(int)

        grouped = amount.groupby(hour)
        self.global_amount_mean = float(amount.mean())
        self.global_amount_std = float(amount.std()) or 1.0
        self.hour_stats = {
            int(h): (float(g.mean()), float(g.std()) or self.global_amount_std)
            for h, g in grouped
        }

        engineered = self.engineer(train)
        # RobustScaler, e não StandardScaler: Amount tem outliers extremos que
        # deslocariam média e desvio.
        self.scaler = RobustScaler().fit(engineered[self.scaling_columns])

        self.feature_names = [
            column
            for column in engineered.columns
            if column not in {"Time", "Class"}
        ]
        return self

    def transform(self, frame: pd.DataFrame) -> pd.DataFrame:
        if self.scaler is None:
            raise RuntimeError("Preprocessor não ajustado. Chame fit() antes.")
        engineered = self.engineer(frame)
        engineered[self.scaling_columns] = self.scaler.transform(
            engineered[self.scaling_columns]
        )
        return engineered[self.feature_names]


def temporal_split(
    frame: pd.DataFrame, train_frac: float, val_frac: float
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Divide por posição depois de ordenar por tempo. Sem embaralhamento."""
    ordered = frame.sort_values("Time", kind="mergesort").reset_index(drop=True)
    n = len(ordered)
    train_end = int(n * train_frac)
    val_end = train_end + int(n * val_frac)
    return (
        ordered.iloc[:train_end].copy(),
        ordered.iloc[train_end:val_end].copy(),
        ordered.iloc[val_end:].copy(),
    )


def _assert_no_leakage(
    train: pd.DataFrame, val: pd.DataFrame, test: pd.DataFrame
) -> None:
    """Invariantes que, se violadas, invalidam todas as métricas do projeto."""
    if not (train["Time"].max() <= val["Time"].min()):
        raise LeakageError("Sobreposição temporal entre treino e validação.")
    if not (val["Time"].max() <= test["Time"].min()):
        raise LeakageError("Sobreposição temporal entre validação e teste.")

    for name, part in (("treino", train), ("validação", val), ("teste", test)):
        positives = int(part["Class"].sum())
        if positives == 0:
            # Com 492 positivos em 284.807 linhas e corte cronológico, ter positivo
            # em cada partição não é garantido a priori — precisa ser verificado.
            raise LeakageError(f"Partição de {name} não contém nenhuma fraude.")


def prepare(save: bool = True, config: dict | None = None) -> dict[str, Any]:
    """Executa a preparação completa e devolve as partições prontas."""
    config = config or load_config()
    target = cfg(config, "features.target_col")

    frame = load_raw()

    with timed(logger, "Particionamento cronológico"):
        train, val, test = temporal_split(
            frame,
            train_frac=cfg(config, "data.split.train_frac"),
            val_frac=cfg(config, "data.split.val_frac"),
        )
        _assert_no_leakage(train, val, test)

    # Duplicatas exatas saem apenas do treino: no teste, elas fazem parte da
    # distribuição que o modelo enfrentaria de verdade (ADR-0005).
    duplicates = int(train.duplicated().sum())
    duplicate_frauds = int(train[train.duplicated()][target].sum())
    if cfg(config, "data.split.drop_duplicates_in_train_only"):
        train = train.drop_duplicates().reset_index(drop=True)
    logger.info(
        "Duplicatas exatas removidas do treino: %d (das quais %d fraudes)",
        duplicates,
        duplicate_frauds,
    )

    with timed(logger, "Ajuste do pré-processador (somente no treino)"):
        preprocessor = Preprocessor(
            amount_col=cfg(config, "features.amount_col"),
            scaling_columns=list(cfg(config, "features.scaling.columns")),
            pca_aggregates=bool(cfg(config, "features.engineered.pca_aggregates", False)),
        ).fit(train)

    splits = {}
    amount_col = cfg(config, "features.amount_col")
    for name, part in (("train", train), ("val", val), ("test", test)):
        splits[f"X_{name}"] = preprocessor.transform(part)
        splits[f"y_{name}"] = part[target].reset_index(drop=True)
        # Valor monetário original, alinhado linha a linha com a partição. O custo da
        # política é monetário e precisa acompanhar exatamente as mesmas linhas — depois
        # da remoção de duplicatas no treino, reconstruí-lo por fora sairia desalinhado.
        splits[f"amount_{name}"] = part[amount_col].to_numpy()

    summary = {
        "n_features": len(preprocessor.feature_names),
        "features": preprocessor.feature_names,
        "duplicates_removed_from_train": duplicates,
        "duplicate_frauds_removed": duplicate_frauds,
        "splits": {
            name: {
                "n_rows": int(len(part)),
                "n_positives": int(part[target].sum()),
                "positive_rate": float(part[target].mean()),
                "time_start": float(part["Time"].min()),
                "time_end": float(part["Time"].max()),
            }
            for name, part in (("train", train), ("val", val), ("test", test))
        },
    }

    for name, info in summary["splits"].items():
        logger.info(
            "%-5s: %6d linhas · %3d fraudes (%.4f%%) · t=[%.0f, %.0f]",
            name,
            info["n_rows"],
            info["n_positives"],
            100 * info["positive_rate"],
            info["time_start"],
            info["time_end"],
        )

    if save:
        reports_dir = resolve_path(cfg(config, "paths.reports_dir"))
        reports_dir.mkdir(parents=True, exist_ok=True)
        path = reports_dir / "preprocessing_summary.json"
        path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.info("Resumo gravado em %s", path.relative_to(resolve_path(".")))

    return {**splits, "preprocessor": preprocessor, "summary": summary}


if __name__ == "__main__":
    result = prepare()
    print(f"\nAtributos ({result['summary']['n_features']}):")
    print(", ".join(result["summary"]["features"]))
