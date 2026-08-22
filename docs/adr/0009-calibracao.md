# ADR-0009 — Calibrar explicitamente as probabilidades do modelo

**Status:** Aceita
**Data:** 2026-08-20
**Alterada por:** [ADR-0022](0022-protocolo-de-medicao.md) (invariante e precisão numérica) ·
[ADR-0026](0026-reajuste-em-treino-mais-validacao.md) (conjunto de ajuste)

## Contexto

A saída de um classificador é frequentemente tratada como probabilidade, mas raramente é.
Dois fatores deste projeto garantem que **não** será:

1. **Gradient boosting não produz probabilidades calibradas.** Otimiza uma perda que
   privilegia ordenação correta, e tende a empurrar as previsões para os extremos.
2. **A ponderação de classe (ADR-0006) distorce deliberadamente a escala.** Ao aumentar o
   peso dos positivos, o modelo passa a superestimar sistematicamente a probabilidade de
   fraude. Um escore de 0,9 pode corresponder a uma frequência real bem menor.

Enquanto o uso do modelo for apenas ordenar transações, isso não importa — PR-AUC e
ROC-AUC dependem só da ordem. Passa a importar no momento em que o escore vira **decisão
com faixas** (ADR-0010): definir uma faixa de "revisão manual" entre dois limiares só faz
sentido se os valores tiverem significado de frequência. Com escores não calibrados, os
cortes são arbitrários e não se transferem entre reexecuções nem entre períodos.

Calibração também é o que permite converter escore em **perda monetária esperada**, base
do critério econômico do limiar.

## Decisão

Calibrar as probabilidades do modelo principal e avaliar explicitamente a qualidade da
calibração.

- **Método:** regressão isotônica, ajustada sobre as **predições fora-de-fold**, nunca no
  treino (onde o modelo está sobreajustado) nem no teste (que seria vazamento).

  > **Alterado pela [ADR-0026](0026-reajuste-em-treino-mais-validacao.md):** o ajuste era
  > feito na partição de validação. Como o modelo final passou a treiná-la, sobrou apenas
  > o fora-de-fold como conjunto não visto. O efeito colateral está medido e registrado:
  > o calibrador é estimado sobre modelos de fold mais fracos e aplicado a um modelo final
  > mais confiante, e a diferença de distribuição comprime a massa no primeiro platô.
- **Comparação:** avaliamos também a calibração sigmoide (Platt) e mantemos a que
  apresentar melhor Brier score na validação, registrando ambos os resultados.
- **Métricas de calibração:** Brier score e erro de calibração esperado (ECE), antes e
  depois, mais **diagrama de confiabilidade** como evidência visual.
- **Invariante a verificar:** o mapeamento precisa ser **monotônico não decrescente**,
  checado de forma exata sobre os escores ordenados.

  > **Corrigido pela [ADR-0022](0022-protocolo-de-medicao.md):** a formulação original
  > dizia que a calibração "não deve alterar PR-AUC nem ROC-AUC, por ser transformação
  > monotônica". **É falsa.** A isotônica é monotônica mas não estritamente: colapsa
  > faixas de escore no mesmo valor, e os empates resultantes deslocam métricas de
  > ordenação — o ROC-AUC do XGBoost caiu de 0,9802 para 0,9472 só por ser medido sobre
  > o escore calibrado. A correção tem duas partes: métricas de ordenação passam a ser
  > medidas sobre o **escore bruto**, e o invariante verifica **monotonicidade do
  > mapeamento**, com tolerância derivada da resolução do tipo (o `predict_proba` do
  > XGBoost é float32, e 1 ULP bastava para uma checagem rígida acusar violação
  > inexistente).

## Alternativas consideradas

- **Não calibrar.** É o que a maioria dos trabalhos sobre esta base faz, e não afetaria as
  métricas exigidas pela rubrica. Descartada porque inviabiliza a política de três faixas
  e a leitura econômica, que são o diferencial do projeto.
- **Calibração sigmoide (Platt) como padrão.** Mais estável com poucos positivos, por ter
  só dois parâmetros. Mantida como candidata comparada, não como padrão fixo: assume forma
  sigmoide do desvio, que nem sempre descreve a distorção do boosting.
- **`CalibratedClassifierCV` com validação cruzada interna.** Seria a via padrão do
  scikit-learn. Descartada porque sua reamostragem interna é embaralhada e conflita com o
  particionamento cronológico da ADR-0003; usamos a partição de validação cronológica já
  reservada.

## Consequências

- Um passo a mais no pipeline e um artefato adicional a versionar e servir junto ao
  modelo. O objeto servido em produção passa a ser o par modelo + calibrador.
- A regressão isotônica é não paramétrica e pode sobreajustar com poucos positivos
  (~74 na validação). O risco é real, e é exatamente por isso que comparamos com Platt em
  vez de assumir isotônica de saída.
- Passamos a poder afirmar coisas como "entre as transações com escore acima de 0,8,
  aproximadamente 80% são fraude" — afirmação que, sem calibração, seria falsa.
- Rende ao relatório uma seção de análise que a maioria dos trabalhos desta base não tem,
  e sustenta diretamente as rubricas de modelagem e de operacionalização.
