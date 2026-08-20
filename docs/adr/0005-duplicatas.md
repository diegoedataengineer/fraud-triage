# ADR-0005 — Remover duplicatas exatas apenas na partição de treino

**Status:** Aceita
**Data:** 2026-08-20

## Contexto

A inspeção da base revelou **1.081 linhas exatamente duplicadas** considerando as 31
colunas. O número é sensível ao conjunto de colunas: descartando `Time`, saltam para
9.144 — sinal de que boa parte são transações distintas que coincidem nos valores de PCA
e no valor monetário, e não registros repetidos.

Duplicatas têm dois efeitos opostos, e é preciso escolher qual evitar:

- **No treino**, inflam artificialmente o peso de certos padrões e, se a mesma linha
  aparecer em partições diferentes, produzem vazamento — o modelo é avaliado sobre algo
  que memorizou.
- **No teste**, removê-las distorce a distribuição avaliada. Se transações idênticas de
  fato ocorrem na operação real, o teste deve refleti-las; limpá-lo é medir um mundo que
  não existe.

Com apenas 492 positivos, descartar positivos duplicados sem critério é caro.

## Decisão

Remover duplicatas exatas (considerando **todas** as colunas, `Time` incluída)
**somente na partição de treino**. Validação e teste permanecem intactos.

Como o particionamento é cronológico e `Time` participa da chave, duplicatas exatas não
podem atravessar partições — a possibilidade de vazamento por essa via já está eliminada
pela ADR-0003. A remoção no treino trata do peso amostral, não do vazamento.

A contagem de duplicatas removidas, e quantas eram fraudes, é registrada nos artefatos
de pré-processamento e reportada na análise exploratória.

## Alternativas consideradas

- **Remover duplicatas de toda a base.** É o procedimento mais comum na literatura deste
  dataset. Descartada por alterar a distribuição de teste e produzir métrica que não
  corresponde ao que o modelo enfrentaria.
- **Não remover nada.** Simples e sem risco de descartar sinal escasso. Descartada porque
  linhas repetidas no treino distorcem a função de perda sem acrescentar informação.
- **Deduplicar ignorando `Time`.** Removeria as 9.144. Descartada por ser agressiva
  demais: transações diferentes podem legitimamente coincidir em componentes de PCA e
  valor, e descartá-las eliminaria observações reais — inclusive positivos, que são
  escassos.

## Consequências

- Treino e teste passam a ter tratamentos diferentes, o que precisa ser dito com clareza
  no relatório para não parecer inconsistência metodológica.
- O conjunto de treino encolhe marginalmente (1.081 linhas em ~199 mil, cerca de 0,5%).
- As métricas de teste ficam levemente mais conservadoras que as de trabalhos que
  deduplicam tudo — diferença esperada e defensável.
- A contagem de duplicatas por classe vira um dado da EDA, útil para discutir qualidade
  da base.
