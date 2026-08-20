# Spec 003 — Métricas, política de três faixas e análise de sensibilidade

**ADRs relacionadas:** [0004](../adr/0004-metrica-primaria.md) ·
[0010](../adr/0010-politica-de-decisao.md)

## `src/evaluate.py`

**Entrada:** modelo + calibrador, todas as partições
**Saída:** `reports/evaluation_summary.json` e figuras

### Métricas reportadas

Calculadas sobre o **teste**, tocado uma única vez, ao final.

| Métrica | Papel | Mínimo da rubrica |
|---|---|---|
| PR-AUC (`average_precision`) | seleção (ADR-0004) | — |
| ROC-AUC | relato | **≥ 0,95** |
| Recall (classe positiva) | relato | **≥ 0,75** |
| Precision (classe positiva) | relato | **≥ 0,80** |
| F1 (classe positiva) | relato | — |
| Brier score, ECE | qualidade da calibração | — |

Precisão, recall e F1 são sempre da **classe positiva**, jamais médias ponderadas — a
média ponderada é dominada pela classe majoritária e ficaria acima de 0,99 sem
significar nada.

### Validação cruzada

`TimeSeriesSplit` com 5 folds sobre treino+validação (ADR-0003). Reportar **média e
desvio-padrão** entre folds, nunca um valor isolado. O desvio alimenta o critério de
adoção da Spec 002.

### Figuras obrigatórias

Curva Precision-Recall (com a linha de referência aleatória em 0,0017), curva ROC, matriz
de confusão no ponto de operação escolhido, distribuição dos escores por classe, curva de
aprendizado e diagrama de confiabilidade.

## `src/policy.py`

Implementa a política de três faixas da ADR-0010.

### Modelo de custo

Parâmetros em `config.policy.costs`:

| Parâmetro | Significado |
|---|---|
| `fraud_loss_multiplier` | fração do `Amount` perdida em fraude não detectada (padrão 1,0) |
| `manual_review_cost` | custo fixo por transação encaminhada à revisão |
| `false_block_cost` | custo fixo por bloqueio indevido de transação legítima |
| `review_capacity_pct` | teto de transações encaminháveis à revisão, em % do volume |

Custo total esperado, dados os limiares `t_baixo` e `t_alto`:

```
custo(t_baixo, t_alto) =
      Σ  Amount_i · fraud_loss_multiplier      sobre fraudes com  p_i < t_baixo
    + Σ  manual_review_cost                    sobre  t_baixo ≤ p_i < t_alto
    + Σ  false_block_cost                      sobre legítimas com  p_i ≥ t_alto
```

Fraudes na faixa de revisão são consideradas detectadas (o analista as identifica); esta
premissa é declarada no relatório, pois assume revisão perfeita.

### Otimização

Busca em grade sobre pares `(t_baixo, t_alto)` com `t_baixo < t_alto`, **na partição de
validação**, minimizando o custo sujeito a:

```
fração encaminhada à revisão  ≤  review_capacity_pct
```

Se nenhum par satisfizer a restrição, falhar explicitamente em vez de ignorá-la em
silêncio.

### Análise de sensibilidade

Como os custos são arbitrados, o resultado só é confiável se for robusto. Variar:

- a razão `fraud_loss / false_block` em pelo menos cinco níveis;
- `review_capacity_pct` em pelo menos cinco níveis.

Saída: mapa de calor do custo total e das faixas resultantes, mais discussão de quais
conclusões se sustentam sob variação. **A conclusão do relatório é o comportamento da
política, não um par específico de números.**

### Critérios de aceite

- Limiares determinados **exclusivamente** na validação — teste automatizado.
- `t_baixo < t_alto`, ambos em `[0, 1]`.
- A restrição de capacidade é respeitada na validação.
- O recorte binário equivalente (`p ≥ t_baixo` como positivo) atinge os mínimos da
  rubrica no teste. **Se não atingir, é bloqueio de entrega**, e a causa deve ser
  investigada antes de qualquer ajuste na política.
- `reports/policy_summary.json` grava limiares, custo, distribuição por faixa e a matriz
  de sensibilidade.
