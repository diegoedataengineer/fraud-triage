# ADR-0001 — Adotar a Trilha A (aprendizado supervisionado) no domínio de detecção de fraude

**Status:** Aceita
**Data:** 2026-08-20

## Contexto

A Sistematização oferece cinco trilhas (A a E) e atribui **7 dos 40 pontos** ao
"atendimento às métricas mínimas da trilha escolhida". As métricas mínimas não têm
dificuldade equivalente entre as trilhas, e essa assimetria é decisiva:

| Trilha | Métricas mínimas | Avaliação de risco |
|---|---|---|
| A1 — Inadimplência | AUC ≥ 0,75 · **F1 ≥ 0,65** · Recall ≥ 0,60 | F1 refere-se à classe positiva; o teto realista dessa base fica em torno de 0,55 |
| A2 — Fraude | AUC ≥ 0,95 · Recall ≥ 0,75 · Precision ≥ 0,80 | Alcançável com folga por gradient boosting com limiar ajustado |
| A3 — Churn | AUC ≥ 0,82 · Acc ≥ 0,80 · **F1 ≥ 0,68** | Apertado na classe de churn, cujo teto usual é ~0,65 |
| C/D/E — Deep Learning | Acurácia alta | Treino longo e reexecução frágil no Colab gratuito |

O último ponto pesa porque **o notebook será reexecutado durante a correção** e
"diferenças significativas nas métricas poderão resultar em desconto na nota". Uma
solução cujas métricas ficam marginalmente acima do mínimo carrega risco de reprovar no
próprio critério que deveria pontuar.

O professor publicou um repositório de referência no mesmo domínio
(`fraud-detection-mlops`), disponibilizado **para observação**. Isso torna o domínio
mais legível para a banca, mas exige que a nossa solução tenha identidade técnica
própria — não basta reproduzir a referência.

## Decisão

Adotar a **Trilha A — Aprendizado Supervisionado**, no problema **A2, detecção de
fraude em transações de cartão de crédito**.

A diferenciação em relação à referência não vem de trocar o dataset, e sim do
enquadramento do problema: em vez de otimizar um classificador binário com um limiar de
corte único, tratamos a saída do modelo como insumo de uma **política de triagem
operacional sujeita a restrição de capacidade de revisão manual** (ADR-0010), sustentada
por probabilidades explicitamente calibradas (ADR-0009). São decisões que mudam o
objeto de otimização, não apenas a implementação.

## Alternativas consideradas

- **A1 — Inadimplência (UCI id 350).** Distanciaria mais da referência e dispensa
  autenticação. Descartada porque `F1 ≥ 0,65` na classe positiva é agressivo para essa
  base: colocaria 7 pontos em risco por uma diferenciação que obtemos de outra forma.
- **A3 — Churn Telco.** Base pequena e rápida de treinar. Descartada por dois motivos:
  `F1 ≥ 0,68` na classe de churn é apertado, e a distribuição primária é o Kaggle, que
  exige credencial e conflita com a exigência de execução sem autenticação.
- **Trilha E — Transformers (AG News).** Tecnicamente mais vistosa e distante da
  referência. Descartada pelo prazo de três dias combinado à exigência de reexecução
  integral: fine-tuning de DistilBERT no Colab gratuito depende de disponibilidade de
  GPU que não controlamos no momento da correção.

## Consequências

- As métricas mínimas deixam de ser o risco dominante do projeto, e o esforço se
  desloca para os outros 33 pontos da rubrica.
- O desbalanceamento extremo (0,17% de positivos) passa a ser o problema técnico
  central, e contamina praticamente todas as decisões seguintes — métrica (ADR-0004),
  amostragem (ADR-0006) e limiar (ADR-0010).
- Assumimos o ônus de demonstrar originalidade frente a uma referência pública no mesmo
  domínio. O relatório precisa explicitar em que a nossa formulação difere e por quê.
- As features `V1`–`V28` são componentes de PCA anonimizados, o que limita a
  interpretabilidade semântica. Isso é tratado abertamente na ADR-0011 em vez de
  mascarado.
