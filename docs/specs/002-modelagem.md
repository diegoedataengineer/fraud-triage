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

Otimiza **recall médio na região de precisão aceitável**, por validação cruzada temporal
sobre treino + validação ([ADR-0021](../adr/0021-objetivo-do-tuning.md)):

```
objetivo = média_folds( max{ recall : precisão ≥ evaluation.rubric_minimums.precision } )
```

PR-AUC entra como desempate de peso desprezível. O piso de precisão é lido da mesma chave
que a aceitação usa, para que tuning e cobrança sejam o mesmo número.

A validação cruzada substitui o split único porque 56 positivos não sustentam 50
tentativas de busca: uma execução anterior atingiu 0,8811 na validação e caiu para 0,6806
no teste. Espaço de busca conforme
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

**teste t pareado** sobre as diferenças de PR-AUC por fold, unilateral
([ADR-0020](../adr/0020-criterio-de-adocao.md)):

```
t = média(diferenças) / (desvio(diferenças) / √n)     adota-se o principal se p < α
```

Pareado porque os dois modelos correm nos mesmos folds. `α` vem de
`evaluation.adoption_alpha`. Wilcoxon é reportado como apoio — com n=5 seu menor p-valor
alcançável é 0,03125, então não decide sozinho.

Se o baseline vencer ou empatar, ele é adotado e isso é reportado como achado, não
escondido (ADR-0007).

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

- **Invariante:** o mapeamento é **monotônico não decrescente**, verificado de forma
  exata sobre os escores ordenados, com tolerância derivada de `np.finfo(dtype).eps` e
  da escala dos valores. **Teste automatizado, não conferência manual.**
- **Degradação de ranking** limitada por `calibration.max_ranking_degradation`, para
  detectar empates em excesso sem reprovar arredondamento legítimo.
- Escores convertidos a **float64** antes de calibrar: o `predict_proba` do XGBoost é
  float32, e 1 ULP bastava para uma checagem rígida acusar violação inexistente.

  > Exigir que PR-AUC e ROC-AUC ficassem inalteradas — como esta spec dizia — está
  > **errado**: a isotônica é monotônica mas não estritamente, e os empates que ela cria
  > deslocam métricas de ordenação ([ADR-0022](../adr/0022-protocolo-de-medicao.md)).
- O calibrador nunca vê o conjunto de teste — coberto por teste.
- O Brier score do método escolhido é menor que o do escore bruto na validação.
- O artefato persistido é o par (modelo, calibrador): é ele que vai a produção.
