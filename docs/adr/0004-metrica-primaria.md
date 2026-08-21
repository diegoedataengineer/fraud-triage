# ADR-0004 — Usar PR-AUC como métrica primária de seleção

**Status:** Aceita
**Data:** 2026-08-20
**Alterada por:** [ADR-0021](0021-objetivo-do-tuning.md) (papel na busca de hiperparâmetros) ·
[ADR-0022](0022-protocolo-de-medicao.md) (medida sobre escore bruto)

## Contexto

Com 0,1727% de positivos, as métricas usuais deixam de informar:

- **Acurácia** é inútil: prever "não é fraude" para tudo alcança 99,83% e não detecta
  nada. Qualquer discussão baseada em acurácia neste problema é ruído.
- **ROC-AUC** é enganosa sob desbalanceamento extremo. A taxa de falsos positivos tem no
  denominador as 284.315 transações legítimas, então mesmo milhares de falsos positivos
  mal deslocam o eixo. O resultado é uma curva otimista: valores acima de 0,97 são
  rotineiros neste dataset e não discriminam bem entre modelos.

A **precisão média (PR-AUC)** trabalha com precisão e recall, ambas condicionadas à classe
positiva. Nenhuma das duas tem as transações legítimas no denominador, então a métrica
responde de fato ao que muda a operação: quantas fraudes pegamos e a que custo de alarme
falso. É a métrica adequada a positivos raros.

Há uma tensão a administrar: a rubrica exige `AUC-ROC ≥ 0,95`, `Recall ≥ 0,75` e
`Precision ≥ 0,80`. Ou seja, a ROC-AUC precisa ser **reportada** e atingida, mesmo não
sendo boa para **selecionar** modelo.

## Decisão

Separar os dois papéis:

- **Seleção e ajuste** — PR-AUC (`average_precision`) orienta a comparação entre
  modelos e o early stopping. É independente de limiar, o que é essencial porque o
  limiar é decidido depois e por critério econômico (ADR-0010).

  > **Alterado pela [ADR-0021](0021-objetivo-do-tuning.md):** PR-AUC deixou de ser o
  > objetivo da **busca de hiperparâmetros**, que passou a otimizar recall na região de
  > precisão exigida. O motivo é desalinhamento: PR-AUC resume a curva inteira,
  > inclusive regiões que a operação nunca usaria. PR-AUC segue como métrica de relato,
  > como critério de desempate na busca, e como base da comparação entre modelos
  > ([ADR-0020](0020-criterio-de-adocao.md)).
- **Relato** — ROC-AUC, precisão, recall, F1 e matriz de confusão são reportados no
  conjunto de teste, tanto para atender à rubrica quanto para dar leitura operacional.
  PR-AUC e ROC-AUC são calculadas sobre o **escore bruto**, não o calibrado
  ([ADR-0022](0022-protocolo-de-medicao.md)) — são métricas de ordenação, e a
  calibração introduz empates que as deslocam sem que o modelo tenha mudado.

A validação cruzada usa `TimeSeriesSplit` com 5 folds, coerente com a ADR-0003, e
reportamos média e desvio-padrão entre folds — nunca um número isolado, dado que a
contagem de positivos por fold é pequena o bastante para gerar variância relevante.

## Alternativas consideradas

- **ROC-AUC como métrica primária.** É o que a rubrica cobra e o que a literatura do
  dataset mais usa. Descartada para seleção por saturar: com quase todos os candidatos
  acima de 0,97, ela não separa um modelo bom de um ótimo. Continua sendo reportada.
- **F1 da classe positiva.** Diretamente interpretável. Descartada como métrica primária
  por depender de limiar — otimizar F1 embute a premissa de que falso positivo e falso
  negativo custam o mesmo, o que é falso aqui (ADR-0010).
- **Recall a uma precisão fixa.** Muito próxima da leitura operacional. Descartada como
  métrica única por descartar informação sobre o resto da curva, justamente o que a
  política de três faixas precisa enxergar.
- **Custo esperado em unidades monetárias.** É o objetivo final de negócio. Descartada
  como métrica de seleção por depender de premissas de custo arbitradas; ela entra na
  decisão do limiar, onde as premissas ficam explícitas e sujeitas a análise de
  sensibilidade.

## Consequências

- Os valores de PR-AUC serão visivelmente menores que os de ROC-AUC (esperado na casa de
  0,7–0,85 contra 0,97+). O relatório precisa explicar essa diferença, sob pena de
  parecer um resultado pior do que é.
- Ganhamos capacidade de discriminar entre modelos candidatos, que era o objetivo.
- Como PR-AUC independe de limiar, a escolha do ponto de corte fica isolada em uma
  decisão própria, com critério econômico explícito, em vez de embutida na métrica.
- O relatório carrega duas famílias de métricas, com risco de confundir o leitor. Mitigado
  declarando desde o início qual delas decide e qual descreve.
