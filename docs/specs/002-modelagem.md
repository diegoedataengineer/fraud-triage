# Spec 002 — Baseline, modelo principal, tuning e calibração

**ADRs relacionadas:** [0006](../adr/0006-desbalanceamento.md) ·
[0007](../adr/0007-baseline-obrigatorio.md) · [0008](../adr/0008-modelo-principal.md) ·
[0009](../adr/0009-calibracao.md)

## `src/train.py`

### Baseline — regressão logística

Treinado sempre, sob o mesmo particionamento e pré-processamento do modelo principal.
`class_weight="balanced"`, `max_iter` suficiente para convergir. Registrar se houve
aviso de não convergência — um baseline que não convergiu não é comparação válida.

Salva os coeficientes em `reports/baseline_coefficients.json`, usados como leitura
independente de importância na Spec 004.

### Modelo principal — XGBoost com Optuna

Otimiza **PR-AUC na validação** (ADR-0004), com early stopping. Espaço de busca conforme
ADR-0008, com limites em `config/config.yaml`.

Regras que a implementação deve respeitar:

- O amostrador do Optuna recebe a semente de `config.project.random_seed`.
- Cada tentativa treina no treino e avalia na validação. **O teste não é tocado.**
- Registrar, por tentativa: parâmetros, PR-AUC de treino, PR-AUC de validação e número de
  árvores efetivamente usado após early stopping.
- Ao final, gravar o **gap de generalização** (PR-AUC treino − validação) do melhor
  modelo em `reports/training_summary.json`, inclusive quando desfavorável.

### Critério de adoção

O modelo principal só substitui o baseline se:

```
PR_AUC_val(principal) − PR_AUC_val(baseline) > desvio_padrao_folds(TimeSeriesSplit)
```

Ganho inferior à variância do próprio experimento não é ganho. Se o baseline vencer ou
empatar, ele é adotado e isso é reportado como achado, não escondido (ADR-0007).

## `src/calibration.py`

**Entrada:** modelo treinado, partição de **validação**
**Saída:** calibrador ajustado, métricas em `reports/calibration_summary.json`

### Comportamento

1. Obter as probabilidades brutas do modelo sobre a validação.
2. Ajustar **regressão isotônica** e **calibração sigmoide (Platt)** — ambas somente
   sobre a validação (nunca treino, nunca teste).
3. Calcular, para bruto, isotônico e sigmoide: **Brier score** e **ECE** (10 faixas de
   igual frequência).
4. Selecionar o método de menor Brier na validação. Registrar os três resultados, não
   apenas o vencedor.
5. Gerar o **diagrama de confiabilidade** comparando antes e depois em
   `reports/figures/`.

### Critérios de aceite

- **Invariante:** PR-AUC e ROC-AUC não mudam em mais de 1e-6 após a calibração. A
  calibração é monotônica; se as métricas de ordenação mudarem, há erro de
  implementação. **Este é um teste automatizado, não uma conferência manual.**
- O calibrador nunca vê o conjunto de teste — coberto por teste.
- O Brier score do método escolhido é menor que o do escore bruto na validação.
- O artefato persistido é o par (modelo, calibrador): é ele que vai a produção.
