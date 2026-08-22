# ADR-0028 — O artefato embarca o calibrador que foi medido

**Status:** Aceita
**Data:** 2026-08-22
**Complementa:** [ADR-0009](0009-calibracao.md) ·
[ADR-0026](0026-reajuste-em-treino-mais-validacao.md) · [ADR-0022](0022-protocolo-de-medicao.md)

## Contexto

A fila de revisão manual do console estava vazia. Em 42.722 transações de teste, a faixa
intermediária recebia **uma**. E fraudes apareciam aprovadas com probabilidade exibida de
`0,000000` — não "baixa", mas exatamente zero, que é uma afirmação de impossibilidade.

A causa não estava na política nem no modelo. O pipeline **ajustava a calibração duas
vezes**, e embarcava a errada:

| Onde | Ajustada sobre | Destino |
|---|---|---|
| `src/evaluate.py` | fora-de-fold | métricas, limiares da política, relatório |
| `run_pipeline.py` | **validação** | **o artefato**, as figuras, a sensibilidade |

Desde a [ADR-0026](0026-reajuste-em-treino-mais-validacao.md) o modelo final treina em
treino + validação. A validação, portanto, **não é mais um conjunto não visto**. Sobre
dado já visto os escores são quase perfeitamente separáveis, e a isotônica ajustada ali
degenera numa função degrau de quatro nós:

```
X_thresholds_ = [6,0e-06   0,657894   0,868190   0,999586]
y_thresholds_ = [0         0          1          1       ]
```

O efeito no teste: **99,90% das transações mapeadas para exatamente 0,0** e apenas **7
valores distintos**. Uma fraude com escore bruto `0,53` — percentil 99,88, corretamente
ranqueada entre as mais suspeitas — recebia probabilidade `0,000000`.

O dano decisivo é de escala. Os limiares `t_low = 0,0286` e `t_high = 0,5714` foram
calculados sobre a escala **fora-de-fold** e passaram a ser aplicados sobre **outra
escala**. Não sobrava ninguém entre eles. A política de três faixas — a tese do trabalho —
operava como duas.

### Por que nada acusou

Havia uma guarda para isto, `max_ranking_degradation`, e ela **passou**: queda de PR-AUC
de 0,00095, muito abaixo do limite de 0,02.

Com base de 0,17%, PR-AUC e ROC-AUC quase não se movem quando a massa negativa colapsa.
É possível esmagar 99,9% das transações num único valor sem que essas métricas registrem.
A guarda existia para pegar exatamente este defeito e era cega a ele.

A [ADR-0022](0022-protocolo-de-medicao.md) chegou a notar que a isotônica
cria empates — e resolveu o problema **para a medição**, passando as métricas de ordenação
ao escore bruto. Não se percebeu que os mesmos empates quebravam a **decisão**. O sintoma
foi visto; o diagnóstico ficou pela metade.

## Decisão

**Um único ajuste, reaproveitado.** `src/evaluate.py` devolve o calibrador que ajustou, e
`run_pipeline.py` embarca exatamente esse. Foi a duplicação que permitiu que medição e
artefato divergissem sem que nada acusasse.

**Guarda de resolução**, ao lado da de ranking e medindo o que de fato quebra: a fração da
amostra que a calibração colapsa num único valor. Acima de `max_single_value_mass` (0,90),
o pipeline falha com a causa provável no texto do erro.

Os dois cenários reais, verificados:

| Ajuste sobre | Massa no maior valor | Valores distintos | Guarda |
|---|---|---|---|
| fora-de-fold | 21,97% | 25 | passa |
| validação (o defeito) | 99,87% | 2 | **reprova** |

## Consequências

- As métricas da rubrica **não mudam**. ROC-AUC, PR-AUC, precisão, recall e a matriz de
  confusão saem do escore bruto ([ADR-0022](0022-protocolo-de-medicao.md)),
  e Brier, ECE e os limiares já vinham do ajuste correto. O que muda é o que o serviço
  faz — e as figuras de distribuição de escores, confiabilidade e sensibilidade, que eram
  desenhadas com o calibrador errado.
- A faixa de revisão volta a ser alimentada: de 1 transação para 49, e nenhuma fraude do
  fora-de-fold recebe probabilidade zero.
- A faixa continua estreita — cerca de 0,1% do volume, porque a política a dimensiona pela
  capacidade de análise. Rara não é o mesmo que vazia, e a diferença agora é verificável.
- Dois testes fixam o invariante: escores separáveis reprovam, escores com sobreposição
  passam.

## Alternativas consideradas

- **Trocar a isotônica por Platt.** Medida: a faixa de revisão sobe para 174 transações
  com 42 fraudes, mas a faixa de bloqueio esvazia — Platt comprime o topo e o limiar
  superior encosta no teto da distribuição. Troca uma degeneração por outra, e não trata a
  causa, que é calibrar sobre dado visto.
- **Aplicar as faixas ao escore bruto.** Removeria a incompatibilidade de escala, mas o
  modelo de custo multiplica probabilidade por perda esperada: sem probabilidade
  calibrada, os limiares deixam de ter significado econômico.
- **Aliviar os limiares para alargar a faixa.** Trataria o sintoma e falsearia a política,
  que é escolhida por minimização de custo e não por conveniência de demonstração.
