# ADR-0007 — Exigir um baseline interpretável antes do modelo principal

**Status:** Aceita
**Data:** 2026-08-20

## Contexto

É comum um projeto de ML apresentar apenas o modelo mais sofisticado, com métricas boas,
sem responder à pergunta que decide se ele vale a pena: **melhor do que o quê?** Sem
referência, não há como saber se o ganho justifica o custo de operar um modelo complexo —
mais latência, mais dependências, menos interpretabilidade, mais superfície de manutenção.

No caso específico deste dataset, a questão não é retórica. As features `V1`–`V28` são
componentes de PCA, ou seja, **já são projeções lineares descorrelacionadas** do espaço
original. Um modelo linear opera muito bem sobre esse tipo de entrada, e é perfeitamente
possível que a regressão logística fique próxima do gradient boosting. Se ficar, é um
achado relevante — não um fracasso.

## Decisão

Treinar e reportar **sempre** uma **regressão logística com `class_weight="balanced"`**
como baseline, sob exatamente o mesmo particionamento, pré-processamento e protocolo de
avaliação do modelo principal.

O modelo principal só é adotado se apresentar **ganho relevante de PR-AUC** sobre o
baseline na validação. "Relevante" é definido antes de olhar o resultado: ganho superior
ao desvio-padrão entre os folds do `TimeSeriesSplit`. Ganho menor que a própria variância
do experimento não é ganho, é ruído.

Se o baseline for competitivo, esse resultado é reportado como achado central do
relatório, e não minimizado.

## Alternativas consideradas

- **Apenas o modelo principal.** Menos código e narrativa mais direta. Descartada por
  impedir qualquer afirmação sobre a magnitude do ganho — e por deixar a rubrica de
  "modelagem e validação" sem sustentação comparativa.
- **Baseline trivial (classe majoritária ou aleatório estratificado).** Serviria de piso
  absoluto. Descartada por ser piso baixo demais: superá-lo não informa nada. Fica apenas
  como referência de PR-AUC aleatória (igual à taxa de positivos, 0,0017).
- **Comparar muitos modelos (SVM, KNN, Naive Bayes, RF, boosting).** Daria um quadro
  amplo. Descartada pelo prazo e por diluir foco: dois modelos bem executados e bem
  discutidos valem mais que seis superficiais. KNN e regressão logística aparecem no
  benchmark de latência (ADR-0012), onde o ponto é custo de inferência, não acurácia.

## Consequências

- Toda afirmação de desempenho passa a ter referência explícita.
- O baseline serve a um segundo propósito: por ser linear, seus coeficientes oferecem uma
  leitura independente de importância de variáveis, que pode ser confrontada com o SHAP
  do modelo principal (ADR-0011). Convergência entre os dois reforça a explicação.
- Se o baseline vencer ou empatar, adotamo-lo — é mais simples, mais rápido e mais
  interpretável. A decisão fica submetida ao resultado, não à preferência.
- Custo adicional de treino desprezível (segundos).
