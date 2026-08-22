# ADR-0024 — Estabelecer um piso para a perda por fraude

**Status:** Aceita
**Data:** 2026-08-22
**Altera:** [ADR-0010](0010-politica-de-decisao.md) (modelo de custo)

## Contexto

A ADR-0010 definiu a perda por fraude não detectada como proporcional ao `Amount` da
transação. É a formulação intuitiva, e está errada neste domínio.

O problema apareceu ao inspecionar uma decisão no console: uma fraude de **R$ 0,00**
aprovada pelo modelo. Não era dado corrompido. A base tem 1.825 transações de valor zero,
27 delas fraudulentas — a taxa de fraude quando `Amount = 0` é de **1,48%**, contra
0,1727% na base geral. **Oito vezes e meia mais provável.**

É *card testing*: o fraudador roda uma autorização irrisória para confirmar que o cartão
roubado está ativo, antes de partir para a compra real. O padrão domina a distribuição:

| Fraudes no conjunto de teste | Quantidade | Proporção |
|---|---|---|
| Exatamente R$ 0,00 | 2 | 4% |
| Até R$ 1,00 | 20 | **38%** |
| Até R$ 10,00 | 29 | **56%** |

Sob a formulação original, uma fraude de R$ 0,00 gera perda de R$ 0,00. Revisar custa
3,0. **A política nunca pagaria 3 para capturar algo que, na formulação dela, não custa
nada** — e isso valia para mais da metade das fraudes. O otimizador estava se comportando
racionalmente sob um objetivo mal especificado.

O custo real de uma fraude de card testing não é o montante da transação: é a **fraude
seguinte**, que o cartão confirmado como ativo viabiliza. O modelo de custo não enxergava
essa parcela.

## Decisão

Estabelecer um **piso** para a perda por fraude:

```
perda = max(Amount, fraud_loss_floor) × fraud_loss_multiplier
```

com `fraud_loss_floor` ancorado na **média** das fraudes do conjunto de treino:
**R$ 118,65**.

A média, e não a mediana. O piso representa a **perda esperada** da fraude seguinte, e
perda esperada é valor esperado — média. A mediana (R$ 11,86) subestima precisamente
porque a distribuição é assimétrica, e a assimetria é o fenômeno em si, não ruído a ser
aparado.

### Sobre a ordem em que isto foi decidido

Registrado por integridade da análise: o piso foi **inicialmente ancorado na mediana**,
por conservadorismo, e a análise de sensibilidade — que varre cinco valores de piso — foi
construída antes de conhecer o resultado. Ela revelou que o piso só altera o
comportamento da política a partir de aproximadamente R$ 100:

| Piso | `t_low` escolhido |
|---|---|
| R$ 0,00 · R$ 5,00 · R$ 11,86 · R$ 30,00 | 0,3333 |
| R$ 100,00 | 0,1000 |

A troca para a média foi feita **depois** de ver esse resultado, e o argumento que a
sustenta — valor esperado — é anterior e independente dele. A sensibilidade permanece no
relatório justamente para que a conclusão não dependa do valor escolhido: o leitor vê o
comportamento em toda a faixa.

## Alternativas consideradas

- **Manter a perda proporcional apenas ao `Amount`.** É a formulação usual e simples de
  explicar. Descartada por deixar 56% das fraudes economicamente invisíveis à política.
- **Ancorar na mediana (R$ 11,86).** Mais conservador e menos sujeito a outliers.
  Descartada porque perda esperada é média, e a assimetria da distribuição é o fenômeno
  que se quer capturar, não uma distorção.
- **Estimar a perda descontada da cadeia de fraudes subsequentes.** Seria o modelo
  correto. Descartada por não haver, neste dataset, identificador de cartão que permita
  ligar uma transação às seguintes.
- **Custo fixo por fraude, ignorando o `Amount`.** Simplificaria e trataria toda fraude
  como igual. Descartada porque fraudes de valor alto de fato custam mais, e a informação
  existe.

## Consequências

- A política passa a ter incentivo econômico para capturar fraudes de valor irrisório,
  que são a maioria.
- O custo total reportado sobe, porque a mesma decisão passa a ser avaliada sob uma perda
  maior. Números de custo antes e depois **não são comparáveis** entre si.
- O piso é arbitrado, ainda que ancorado em dado. A análise de sensibilidade sobre cinco
  valores existe para que a conclusão do relatório seja o comportamento da política, e
  não o par de limiares obtido com um piso específico.
- Fica documentado que a formulação econômica de um problema pode estar errada sem que
  nada quebre: o otimizador funcionava perfeitamente, apenas otimizava a coisa errada.
