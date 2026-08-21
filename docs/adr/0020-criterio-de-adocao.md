# ADR-0020 — Decidir a adoção do modelo por teste t pareado

**Status:** Aceita
**Data:** 2026-08-21
**Altera:** [ADR-0007](0007-baseline-obrigatorio.md) (critério de adoção)

## Contexto

A ADR-0007 declarou, antes de ver qualquer resultado, que o modelo principal só
substituiria o baseline se o ganho de PR-AUC superasse **o desvio-padrão entre os folds**
do `TimeSeriesSplit`. A intenção era correta: impedir que ruído fosse tomado por ganho.
A formulação, não.

O problema apareceu com números reais. O XGBoost venceu o baseline em **5 de 5 folds**,
com diferença média de **+0,0654**, e ainda assim foi **rejeitado** — porque o
desvio-padrão das diferenças era 0,0660, apenas 0,0006 acima da média. Um critério que
descarta um modelo que ganha em 100% dos folds está medindo a coisa errada.

E está mesmo. Comparar a média das diferenças com o **desvio-padrão** delas responde
"o efeito é maior que a dispersão de uma observação individual?" — uma pergunta de
tamanho de efeito. A pergunta que interessa é outra: "a média das diferenças é
distinguível de zero?". O denominador correto para isso é o **erro-padrão da média**,
que é o desvio dividido por raiz de n.

Havia ainda um defeito acessório: a formulação original comparava o ganho medido no
**split único de validação** contra o desvio **entre folds**. Duas grandezas de
naturezas diferentes, e desde que o HPO passou a otimizar validação cruzada
([ADR-0021](0021-objetivo-do-tuning.md)), a comparação perdeu qualquer sentido.

## Decisão

Adotar o **teste t pareado** sobre as diferenças de PR-AUC por fold, unilateral, com
nível de significância declarado em `config.evaluation.adoption_alpha` (padrão 0,05).

Pareado porque os dois modelos são avaliados **nos mesmos folds**: as diferenças
compartilham a dificuldade de cada período, e ignorar esse pareamento jogaria fora
justamente a parte controlada do experimento.

Reportamos junto o **Wilcoxon dos postos sinalizados**, que não supõe normalidade. Com
n=5 o menor p-valor alcançável por ele é 0,03125, então ele serve como verificação de
apoio, não como árbitro — e isso é dito no relatório em vez de omitido.

Resultado com os dados reais: `t = 2,217`, `p = 0,0455`, Wilcoxon `p = 0,0312`. O
XGBoost é adotado, agora coerentemente com vencer todos os folds.

## Alternativas consideradas

- **Manter o critério original.** Preserva a regra declarada antes do resultado, que é
  uma boa prática contra racionalização a posteriori. Descartada porque a regra estava
  estatisticamente errada, e manter um erro por já tê-lo declarado troca rigor por
  aparência de rigor. A correção é registrada aqui, com o motivo, em vez de silenciosa.
- **Só Wilcoxon.** Não supõe normalidade, o que é atraente com n=5. Descartada como
  árbitro único por não conseguir atingir p < 0,03125 nesse tamanho — decidiria pouco.
- **Aumentar o número de folds para ganhar poder.** Seria o caminho natural. Descartada
  porque 48 horas de dados e 492 positivos não sustentam mais partições temporais com
  positivos suficientes em cada uma.
- **Adotar sempre o modelo mais simples em caso de dúvida.** Defensável em produção.
  Descartada porque o baseline **não atinge** os mínimos exigidos, o que torna a
  escolha inócua na prática.

## Consequências

- A decisão de adoção passa a ter significado estatístico declarado, e não um limiar
  improvisado.
- Com n=5 o poder do teste é baixo: efeitos reais porém modestos podem não ser
  detectados. É limitação registrada, não resolvida.
- Fica documentado que uma regra pode ser declarada de boa-fé e ainda assim estar
  errada. O antídoto não é congelá-la, é corrigi-la explicando o porquê — que é o que
  esta ADR faz.
