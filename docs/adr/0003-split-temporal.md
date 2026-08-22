# ADR-0003 — Particionar os dados cronologicamente, sem embaralhamento

**Status:** Aceita
**Data:** 2026-08-20
**Alterada por:** [ADR-0026](0026-reajuste-em-treino-mais-validacao.md) (uso da validação)

## Contexto

Transações de cartão são um fluxo temporal, e fraude é um fenômeno **adversarial e não
estacionário**: padrões de ataque mudam ao longo do tempo, em resposta às próprias
defesas. Um modelo em produção é sempre treinado no passado e aplicado no futuro.

O `train_test_split` aleatório, padrão na maioria dos tutoriais deste dataset, viola essa
estrutura. Ele permite que uma transação das primeiras horas caia no teste enquanto
transações posteriores estão no treino, expondo o modelo a informação que ele não teria
em operação. O efeito é uma métrica de teste otimista que não se sustenta em produção — a
forma mais comum e mais silenciosa de vazamento neste dataset.

A coluna `Time` (segundos desde a primeira transação) foi verificada como
monotonicamente crescente, cobrindo 48 horas contíguas. Ordenação cronológica é, portanto,
imediata.

## Decisão

Particionar **cronologicamente** por `Time`, sem embaralhar, nas proporções
**70% treino / 15% validação / 15% teste**. Todo ponto de corte é temporal: cada
partição é integralmente posterior à anterior.

Consequências operacionais que decorrem disso e que o pipeline deve respeitar:

- Qualquer estatística de ajuste (escalonamento, calibração, limiar) é estimada
  **exclusivamente no treino** e apenas aplicada às demais partições.
- A validação cruzada usa `TimeSeriesSplit`, nunca `KFold` embaralhado (ADR-0004).
- O **teste é tocado uma única vez**, ao final, para reportar o desempenho.

  > **Alterado pela [ADR-0026](0026-reajuste-em-treino-mais-validacao.md):** a validação
  > servia para busca de hiperparâmetros e calibração. Desde que ambas passaram a vir de
  > validação cruzada, reservá-la deixou de ter função, e o **modelo final treina em
  > treino + validação** — o que importa sobretudo por recência, já que essa janela é a
  > imediatamente anterior ao teste. Calibração, limiares e política passaram a ser
  > ajustados sobre as predições **fora-de-fold**, o único conjunto que ainda satisfaz a
  > condição de não ter sido visto no treino.

## Alternativas consideradas

- **`train_test_split` aleatório estratificado.** Preserva a proporção de fraudes em
  todas as partições, o que é atraente com apenas 492 positivos. Descartada por
  introduzir vazamento temporal e produzir métricas não realizáveis em produção.
- **Validação cruzada estratificada em toda a base.** Reduziria a variância da estimativa,
  relevante dado o número pequeno de positivos. Descartada pelo mesmo motivo: cada fold
  treinaria com dados futuros.
- **Split cronológico com janela deslizante (walk-forward).** Metodologicamente ainda mais
  fiel e permitiria medir degradação ao longo do tempo. Descartada como esquema principal
  porque 48 horas de dados não sustentam janelas múltiplas com positivos suficientes; o
  `TimeSeriesSplit` na validação já captura parte do benefício.

## Consequências

- As métricas reportadas serão **mais baixas** que as de referências que embaralham. Isso
  é resultado desejado, não defeito: elas descrevem o desempenho realizável. O relatório
  precisa dizer isso explicitamente, porque um avaliador acostumado ao número inflado
  pode estranhar.
- A partição de teste contém poucos positivos (~15% de 492, ou cerca de 74 fraudes). As
  métricas da classe positiva terão intervalo de confiança largo, e o relatório deve
  reportar essa incerteza em vez de apresentar um ponto isolado.
- A proporção de fraudes pode variar entre partições, já que não há estratificação. Isso é
  informação legítima — reflete a não estacionariedade real — e será medido e reportado.
- Abre espaço para uma análise honesta de **gap de generalização temporal**: a diferença
  entre validação e teste passa a ter significado interpretável.
