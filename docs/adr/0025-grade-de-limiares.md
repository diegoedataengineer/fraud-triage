# ADR-0025 — Construir a grade de limiares a partir dos valores distintos do escore

**Status:** Aceita
**Data:** 2026-08-22
**Corrige:** [ADR-0010](0010-politica-de-decisao.md) (busca dos limiares)

## Contexto

A busca dos limiares da política percorria uma grade construída por **quantis** do escore
calibrado, entre os percentis 90 e 100, com 200 pontos. O raciocínio parecia sólido: uma
grade uniforme em `[0, 1]` desperdiçaria quase todos os pontos numa região sem transação
alguma, dado o desbalanceamento extremo.

O raciocínio falha quando a distribuição do escore é degenerada. A calibração isotônica
colapsa faixas inteiras de escore em platôs, e nesta execução **42.721 escores de
validação assumem apenas 10 valores distintos**. Uma grade de 200 pontos sobre quantis
produzia **7 limiares** — e, pior, **pulava valores válidos**.

O caso concreto: o limiar `0,3333` existia entre os escores, não aparecia na grade, e era
o de **menor custo total**. O otimizador vinha escolhendo a segunda melhor opção sem
jamais ter avaliado a primeira. Não havia erro de execução — a busca fazia exatamente o
que fora especificado, sobre um conjunto de candidatos incompleto.

## Decisão

Construir a grade a partir dos **próprios valores distintos** do escore:

```python
distintos = np.unique(probabilities)
grade = distintos if len(distintos) <= n_pontos \
        else np.unique(np.quantile(distintos, np.linspace(0.0, 1.0, n_pontos)))
```

Quando os valores distintos cabem no orçamento de pontos, todos são avaliados — com 10
valores, a busca exaustiva é trivial. Quando a distribuição é rica, amostra-se por
quantil **sobre os valores distintos**, e não sobre a amostra, o que preserva a cobertura
sem inflar o custo.

Efeito medido: a política adotada mudou de `t_low = 0,1` para `t_low = 0,3333`, com custo
caindo de 441,55 para 422,23.

## Alternativas consideradas

- **Aumentar o número de pontos da grade por quantil.** Correção aparente. Descartada por
  não resolver: com 10 valores distintos, qualquer quantidade de quantis continua podendo
  pular candidatos, porque o problema é a natureza da amostragem e não sua densidade.
- **Grade uniforme em `[0, 1]`.** Cobriria todo o intervalo. Descartada pelo motivo
  original: com 0,17% de positivos, a quase totalidade dos pontos cairia em regiões vazias.
- **Corrigir a calibração para não produzir platôs.** Atacaria a causa da degeneração.
  Descartada porque os platôs são propriedade da regressão isotônica, que venceu a
  seleção por Brier — trocar a calibração para facilitar a busca seria consertar a coisa
  errada.

## Consequências

- A busca passa a avaliar todos os limiares realmente disponíveis.
- Fica exposto o limite real da política neste projeto: com 10 valores distintos de
  escore, o espaço de decisão é grosseiro, e nenhum ajuste no modelo de custo tem onde
  agir. É a mesma saturação que esvazia a faixa de revisão manual (seção 8.2 do
  relatório).
- Registra-se um modo de falha que não produz erro: uma busca correta sobre um conjunto
  de candidatos incompleto devolve, com confiança, a resposta errada.
