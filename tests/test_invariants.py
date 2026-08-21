"""Testes dos invariantes que, se violados, invalidam todas as métricas do projeto.

Não são testes de estilo. Cada um cobre uma forma conhecida de vazamento ou de erro
silencioso — o tipo que não quebra a execução, apenas produz um número bonito e falso.

Usam dados sintéticos de propósito: a suíte roda na esteira a cada push e não pode
depender de baixar 150 MB nem da disponibilidade do OpenML.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.ingestion import SourceValidationError, parse_arff, validate
from src.preprocessing import LeakageError, Preprocessor, temporal_split, _assert_no_leakage
from src.utils import cfg, load_config, set_seeds


def make_frame(n: int = 3000, n_positives: int = 30, seed: int = 7) -> pd.DataFrame:
    """Frame com o mesmo formato do dataset real, em escala reduzida."""
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame(
        {f"V{i}": rng.normal(size=n) for i in range(1, 29)}
    )
    frame["Time"] = np.arange(n, dtype=float) * 60.0
    frame["Amount"] = rng.lognormal(mean=3.0, sigma=1.2, size=n).round(2)
    frame["Class"] = 0
    # Positivos espalhados por toda a janela, para caírem nas três partições.
    frame.loc[rng.choice(n, size=n_positives, replace=False), "Class"] = 1
    return frame[["Time"] + [f"V{i}" for i in range(1, 29)] + ["Amount", "Class"]]


# ─── particionamento cronológico (ADR-0003) ──────────────────────────────────

def test_split_nao_tem_sobreposicao_temporal():
    train, val, test = temporal_split(make_frame(), 0.70, 0.15)
    assert train["Time"].max() <= val["Time"].min()
    assert val["Time"].max() <= test["Time"].min()


def test_split_preserva_todas_as_linhas():
    frame = make_frame()
    train, val, test = temporal_split(frame, 0.70, 0.15)
    assert len(train) + len(val) + len(test) == len(frame)


def test_split_nao_embaralha():
    """Cada partição precisa continuar ordenada no tempo."""
    for part in temporal_split(make_frame(), 0.70, 0.15):
        assert part["Time"].is_monotonic_increasing


def test_particao_sem_positivo_e_rejeitada():
    """Com positivos raros e corte cronológico, isso não é hipotético."""
    frame = make_frame(n=3000, n_positives=3, seed=1)
    frame["Class"] = 0
    frame.loc[:5, "Class"] = 1  # todos os positivos no início
    train, val, test = temporal_split(frame, 0.70, 0.15)
    with pytest.raises(LeakageError, match="não contém nenhuma fraude"):
        _assert_no_leakage(train, val, test)


# ─── nada é ajustado fora do treino (ADR-0003, ADR-0009) ─────────────────────

def test_escalonador_e_ajustado_somente_no_treino():
    """O ajuste não pode enxergar validação nem teste.

    Verificado por construção: um pré-processador ajustado só no treino produz
    exatamente o mesmo resultado que outro ajustado no treino de um frame cujo
    futuro foi adulterado. Se o ajuste vazasse, os resultados divergiriam.
    """
    frame = make_frame()
    train, val, test = temporal_split(frame, 0.70, 0.15)

    limpo = Preprocessor("Amount", ["Amount", "Amount_log", "Amount_zscore_by_hour"]).fit(train)

    adulterado = frame.copy()
    futuro = adulterado.index >= len(train)
    adulterado.loc[futuro, "Amount"] *= 1000  # explode o futuro
    train_adulterado, _, _ = temporal_split(adulterado, 0.70, 0.15)
    outro = Preprocessor("Amount", ["Amount", "Amount_log", "Amount_zscore_by_hour"]).fit(train_adulterado)

    pd.testing.assert_frame_equal(limpo.transform(val), outro.transform(val))


def test_transform_antes_de_fit_falha():
    with pytest.raises(RuntimeError, match="não ajustado"):
        Preprocessor("Amount", ["Amount"]).transform(make_frame())


def test_time_nao_vira_feature():
    """Time é eixo de particionamento; como feature ensinaria a janela observada."""
    train, _, _ = temporal_split(make_frame(), 0.70, 0.15)
    pre = Preprocessor("Amount", ["Amount", "Amount_log", "Amount_zscore_by_hour"]).fit(train)
    assert "Time" not in pre.feature_names
    assert "Class" not in pre.feature_names


def test_atributos_derivados_existem():
    train, _, _ = temporal_split(make_frame(), 0.70, 0.15)
    pre = Preprocessor("Amount", ["Amount", "Amount_log", "Amount_zscore_by_hour"]).fit(train)
    for atributo in ("Amount_log", "Hour", "Amount_zscore_by_hour"):
        assert atributo in pre.feature_names


def test_transform_e_deterministico():
    train, val, _ = temporal_split(make_frame(), 0.70, 0.15)
    pre = Preprocessor("Amount", ["Amount", "Amount_log", "Amount_zscore_by_hour"]).fit(train)
    pd.testing.assert_frame_equal(pre.transform(val), pre.transform(val))


# ─── validação da fonte (ADR-0002) ───────────────────────────────────────────

ESPERADO = {
    "n_rows": 3000,
    "n_cols": 31,
    "n_positives": 30,
    "positive_rate": 0.01,
    "positive_rate_tolerance": 1e-6,
    "time_span_seconds": 179940,
}


def test_validacao_aceita_fonte_integra():
    validate(make_frame(), ESPERADO)


@pytest.mark.parametrize(
    "corromper, trecho",
    [
        (lambda f: f.iloc[:-1], "linhas"),
        (lambda f: f.assign(Class=0), "positivos"),
        (lambda f: f.assign(Amount=f["Amount"] * -1), "Amount negativo"),
        (lambda f: f.sort_values("Amount"), "monotonicamente"),
        (lambda f: f.drop(columns=["V1"]), "colunas"),
    ],
)
def test_validacao_rejeita_fonte_corrompida(corromper, trecho):
    """Cada divergência precisa falhar com erro, nunca passar em silêncio."""
    with pytest.raises(SourceValidationError, match=trecho):
        validate(corromper(make_frame()), ESPERADO)


def test_arff_sem_marcador_data_falha():
    with pytest.raises(SourceValidationError, match="@data"):
        parse_arff(b"@relation teste\n@attribute Class {0,1}\n1\n")


# ─── configuração e reprodutibilidade (ADR-0013) ─────────────────────────────

def test_config_carrega_e_tem_as_chaves_criticas():
    config = load_config()
    for chave in (
        "project.random_seed",
        "data.arff_url",
        "data.split.train_frac",
        "evaluation.rubric_minimums.roc_auc",
        "policy.costs.manual_review_cost",
        "versioning.registry_dir",
    ):
        assert cfg(config, chave) is not None


def test_chave_ausente_levanta_erro():
    """Configuração incompleta deve falhar cedo, não virar None no meio do treino."""
    with pytest.raises(KeyError, match="nao_existe"):
        cfg(load_config(), "nao_existe.de.jeito.nenhum")


def test_fracoes_do_split_somam_um():
    config = load_config()
    total = sum(
        cfg(config, f"data.split.{nome}") for nome in ("train_frac", "val_frac", "test_frac")
    )
    assert total == pytest.approx(1.0)


def test_semente_torna_a_amostragem_reproduzivel():
    set_seeds(42)
    primeiro = np.random.rand(5)
    set_seeds(42)
    assert np.array_equal(primeiro, np.random.rand(5))
