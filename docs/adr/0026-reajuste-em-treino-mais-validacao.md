# ADR-0026 — Treinar o modelo final em treino + validação

**Status:** Aceita
**Data:** 2026-08-22
**Alterada por:** [ADR-0028](0028-calibracao-do-artefato.md) (consequência sobre a origem da calibração)
**Altera:** [ADR-0003](0003-split-temporal.md) (uso da partição de validação) ·
[ADR-0009](0009-calibracao.md) (conjunto de ajuste da calibração) ·
[ADR-0010](0010-politica-de-decisao.md) (conjunto de otimização da política)

## Contexto

O modelo final treinava apenas na partição de treino, com a validação reservada para
early stopping, calibração e escolha de limiares. Isso faz sentido **enquanto** essas
escolhas ainda estão sendo feitas. Depois que hiperparâmetros e limiar passaram a vir de
validação cruzada ([ADR-0021](0021-objetivo-do-tuning.md),
[ADR-0022](0022-protocolo-de-medicao.md)), reservar a partição deixou de ter função e
passou a ser desperdício.

O desperdício é caro por dois motivos, e o segundo é o decisivo:

**Volume.** São 422 fraudes em treino + validação contra 366 apenas no treino — 15% mais
sinal positivo, num problema onde o positivo é o recurso escasso.

**Recência.** A validação ocupa a janela `t ∈ [132929, 151328]`, imediatamente anterior ao
teste, que começa em `t = 151328`. Fraude é adversarial e não estacionária — a taxa cai
0,1842% → 0,1311% → 0,1217% entre as partições — e num processo assim **o dado rotulado
mais recente é o mais informativo sobre o que vem a seguir**. Era exatamente ele que
estava sendo descartado.

O diagnóstico que motivou a mudança: medido **fora-de-fold**, com 422 positivos e sem
tocar o teste, o modelo já atingia os dois mínimos com folga — `precisão 0,8018` e
`recall 0,8297`, com 64 limiares viáveis. No teste, nenhum. A limitação nunca foi
capacidade do modelo; era transferência temporal.

## Decisão

O modelo final é treinado em **treino + validação**, com os hiperparâmetros já travados
([ADR-0023](0023-hiperparametros-travados.md)).

Isso obriga três ajustes de coerência, porque nenhuma partição não vista sobra:

**Sem early stopping.** O número de árvores faz parte dos hiperparâmetros travados. Parar
cedo por um conjunto que agora está no treino seria vazamento.

**Calibração sobre as predições fora-de-fold.** Cada predição vem de um modelo que não viu
aquela linha. É o único conjunto que preserva a condição de honestidade que a ADR-0009
exigia da validação.

**Política otimizada sobre o fora-de-fold.** Este foi o ponto que quase passou. A política
também é ajuste, e ajustá-la sobre a validação — agora dentro da amostra — produzia
números fantasiosos: *zero fraudes perdidas* e custo de 3,00. Sobre o fora-de-fold, os
mesmos limiares revelam 75 fraudes perdidas em 422. O primeiro conjunto de números não
estava errado por engano de cálculo; media o modelo prevendo o que havia memorizado.

## Resultado medido

| Métrica no teste | Antes | Depois |
|---|---|---|
| Precisão | 0,7500 | **0,7800** |
| Recall | 0,7500 | 0,7500 |
| ROC-AUC | 0,9791 | **0,9856** |
| PR-AUC | 0,7653 | **0,7697** |
| F1 | 0,7500 | **0,7647** |
| Brier | 0,000497 | **0,000425** |

Todas as métricas melhoraram. Os falsos positivos caíram de 13 para 11 — a precisão fica
a **duas transações** do mínimo de 0,80.

## Alternativas consideradas

- **Manter a validação reservada.** Protocolo mais simples de explicar e imune à confusão
  entre conjuntos. Descartada porque, com hiperparâmetros e limiar já vindos de validação
  cruzada, a partição não cumpria mais função alguma.
- **Treinar também no teste.** Daria ainda mais dado e mais recência. **Rejeitada** — é
  vazamento, e destruiria a única estimativa honesta de desempenho.
- **Janela deslizante, treinando só nos períodos mais recentes.** Mais fiel à não
  estacionariedade. Descartada porque 48 horas de dados não sustentam janelas múltiplas
  com positivos suficientes.

## Consequências

- Ganho consistente em todas as métricas, sem tocar o conjunto de teste.
- **Nenhuma partição não vista sobra além do teste.** Toda decisão de ajuste passa a
  depender do fora-de-fold, e esquecer isso em qualquer etapa futura reintroduz vazamento
  silenciosamente — como quase aconteceu com a política.
- Os números de custo da política antes e depois **não são comparáveis**: os anteriores
  eram in-sample.
- Fica registrado o modo de falha mais perigoso encontrado neste projeto: métricas que
  melhoram por estarem sendo medidas sobre dado que o modelo já viu. Elas não parecem
  erradas — parecem excelentes.
