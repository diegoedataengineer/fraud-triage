"""Demonstração funcional: inferência sobre transações que o modelo nunca viu.

Duas fontes, de propósito. As sintéticas mostram o caminho de inferência ponta a ponta
a partir de dados inventados; as reais, retiradas do teste, têm rótulo conhecido e
portanto permitem verificar se a decisão está correta.

**Limitação declarada:** transações geradas a partir de marginais independentes não
preservam a estrutura de correlação entre as componentes de PCA. Servem para exercitar
o caminho de inferência, **não** para avaliar desempenho — medir métricas sobre elas
seria inválido (Spec 006).
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
from faker import Faker

from src import artifacts
from src.utils import cfg, get_logger, load_config

logger = get_logger("demo")

ROTULOS = {
    "approve": "APROVAR",
    "manual_review": "REVISAR",
    "block": "BLOQUEAR",
}


def sinteticas(n: int, seed: int, referencia: pd.DataFrame) -> pd.DataFrame:
    """Gera transações no mesmo formato, com marginais ajustadas ao treino."""
    fake = Faker("pt_BR")
    Faker.seed(seed)
    rng = np.random.default_rng(seed)

    colunas_v = [f"V{i}" for i in range(1, 29)]
    medias = referencia[colunas_v].mean().to_numpy()
    desvios = referencia[colunas_v].std().to_numpy()

    linhas = []
    for _ in range(n):
        valores = {
            coluna: float(rng.normal(m, s))
            for coluna, m, s in zip(colunas_v, medias, desvios)
        }
        valores["Time"] = float(fake.random_int(0, 172_792))
        valores["Amount"] = round(float(rng.lognormal(3.0, 1.3)), 2)
        linhas.append(valores)
    return pd.DataFrame(linhas)[["Time"] + colunas_v + ["Amount"]]


def decidir(artefato: dict, frame: pd.DataFrame) -> pd.DataFrame:
    X = artefato["preprocessor"].transform(frame)
    bruto = artefato["model"].predict_proba(X)[:, 1].astype(np.float64)
    prob = artefato["calibrator"].transform(bruto)
    limiares = artefato["policy"]

    faixa = np.where(
        prob >= limiares["t_high"], "block",
        np.where(prob >= limiares["t_low"], "manual_review", "approve"),
    )
    return pd.DataFrame({"Amount": frame["Amount"].to_numpy(), "prob": prob, "band": faixa})


def main() -> int:
    parser = argparse.ArgumentParser(description="Demonstração de inferência.")
    parser.add_argument("--n", type=int, help="quantidade de transações sintéticas")
    args = parser.parse_args()

    config = load_config()
    artefato = artifacts.load(config=config)
    meta = artefato["metadata"]

    print(f"\nModelo {meta['version']} · limiares "
          f"t_low={artefato['policy']['t_low']:.4f} t_high={artefato['policy']['t_high']:.4f}\n")

    from src.ingestion import load_raw
    from src.preprocessing import temporal_split

    bruto = load_raw()
    treino, _, teste = temporal_split(
        bruto, cfg(config, "data.split.train_frac"), cfg(config, "data.split.val_frac")
    )

    n = args.n or cfg(config, "demo.n_synthetic_transactions")
    frame = sinteticas(n, cfg(config, "demo.faker_seed"), treino)
    resultado = decidir(artefato, frame)

    print("── Transações sintéticas (Faker) ─────────────────────────────")
    print("   Sem rótulo: demonstram o caminho de inferência, não o desempenho.\n")
    for i, linha in resultado.iterrows():
        print(f"   #{i+1:02d}  R$ {linha['Amount']:>10,.2f}   p={linha['prob']:.6f}   "
              f"{ROTULOS[linha['band']]}")

    # Transações reais do teste: rótulo conhecido, previsão verificável.
    n_reais = cfg(config, "demo.n_real_transactions")
    fraudes = teste[teste["Class"] == 1].head(max(1, n_reais // 2))
    legitimas = teste[teste["Class"] == 0].head(n_reais - len(fraudes))
    amostra = pd.concat([fraudes, legitimas])
    reais = decidir(artefato, amostra.drop(columns=["Class"]))
    reais["real"] = amostra["Class"].to_numpy()

    print("\n── Transações reais do conjunto de teste ─────────────────────")
    print("   Rótulo conhecido: aqui a decisão é verificável.\n")
    for i, linha in reais.iterrows():
        rotulo = "FRAUDE" if linha["real"] == 1 else "legítima"
        detectou = linha["band"] in ("manual_review", "block")
        marca = "✓" if detectou == bool(linha["real"]) else "✗"
        print(f"   {marca}  R$ {linha['Amount']:>10,.2f}   p={linha['prob']:.6f}   "
              f"{ROTULOS[linha['band']]:<9} (real: {rotulo})")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
