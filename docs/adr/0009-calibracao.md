# ADR-0009 — Calibrar explicitamente as probabilidades do modelo

**Status:** Aceita
**Data:** 2026-08-20

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

- **Método:** regressão isotônica, ajustada **exclusivamente na partição de validação**,
  nunca no treino (onde o modelo está sobreajustado) nem no teste (que seria vazamento).
- **Comparação:** avaliamos também a calibração sigmoide (Platt) e mantemos a que
  apresentar melhor Brier score na validação, registrando ambos os resultados.
- **Métricas de calibração:** Brier score e erro de calibração esperado (ECE), antes e
  depois, mais **diagrama de confiabilidade** como evidência visual.
- **Invariante a verificar:** a calibração não deve alterar PR-AUC nem ROC-AUC de forma
  relevante, por ser transformação monotônica. Se alterar, há erro de implementação — e
  isso vira um teste automatizado.

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
