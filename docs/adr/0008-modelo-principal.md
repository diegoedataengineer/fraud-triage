# ADR-0008 — Adotar gradient boosting com busca de hiperparâmetros via Optuna

**Status:** Aceita
**Data:** 2026-08-20

## Contexto

O problema é classificação binária sobre 30 features numéricas densas, sem estrutura
espacial ou sequencial que justifique redes neurais, e com desbalanceamento extremo. Para
esse perfil, ensembles de árvores por gradient boosting são o estado da prática: capturam
interações não lineares, lidam bem com escalas distintas e treinam em segundos nesta
escala de dados.

A busca de hiperparâmetros por grade é ineficiente em espaços com muitos parâmetros
contínuos e interdependentes, onde a maior parte do orçamento se gasta em regiões
irrelevantes. Busca bayesiana concentra as tentativas nas regiões promissoras.

Há um risco específico a antecipar: com apenas 492 positivos, gradient boosting **decora**
com facilidade. É esperado observar PR-AUC próximo de 1,0 no treino contra valores
sensivelmente menores na validação. Isso precisa ser combatido por construção do espaço
de busca, não descoberto depois.

## Decisão

Adotar **XGBoost** como modelo principal, com busca de hiperparâmetros por **Optuna**
(amostrador TPE), otimizando **PR-AUC na partição de validação** (ADR-0004), com
**early stopping** por rodadas sem melhora.

O espaço de busca inclui, deliberadamente, os controles de sobreajuste — não apenas
capacidade:

| Parâmetro | Papel |
|---|---|
| `max_depth`, `min_child_weight` | limitam a capacidade de cada árvore |
| `learning_rate`, `n_estimators` | trocam passo por número de rodadas (com early stopping) |
| `reg_alpha`, `reg_lambda` | regularização L1 e L2 |
| `subsample`, `colsample_bytree` | amostragem de linhas e colunas por árvore |
| `scale_pos_weight` | intensidade da ponderação de classe (ADR-0006) |

O número de tentativas é parametrizado em `config/config.yaml`, permitindo execução
reduzida em ambientes limitados sem alterar código.

Comparamos treino e validação a cada execução e **reportamos o gap de generalização**,
inclusive quando desfavorável.

## Alternativas consideradas

- **LightGBM.** Equivalente em desempenho e tipicamente mais rápido. Escolhemos XGBoost
  por ser o que o repositório de referência **não** usa, dando leitura independente do
  mesmo problema; a diferença prática de resultado é pequena e a estrutura do código
  permite trocar via configuração.
- **Random Forest.** Robusto e com menos hiperparâmetros sensíveis. Descartado por
  desempenho tipicamente inferior ao boosting sob desbalanceamento extremo, e por
  produzir probabilidades ainda mais mal calibradas.
- **Busca em grade ou aleatória.** Mais simples de explicar. Descartada por eficiência:
  no mesmo orçamento de tentativas, a busca bayesiana alcança regiões melhores do espaço.
- **Rede neural (MLP).** Descartada por não haver estrutura que a favoreça, por exigir
  mais dados para superar boosting em dados tabulares e por reduzir a interpretabilidade
  sem ganho esperado.

## Consequências

- Ganhamos capacidade de modelar interações não lineares, ao custo de perder leitura
  direta de coeficientes — compensado pelo SHAP (ADR-0011) e pelo baseline (ADR-0007).
- As probabilidades de saída são mal calibradas por construção, tanto pelo boosting
  quanto pela ponderação de classe. A ADR-0009 trata disso.
- A busca com Optuna introduz não determinismo que precisa ser contido por semente fixa
  (ADR-0013), sob pena de a reexecução na correção produzir outro modelo.
- O tempo de treino permanece na casa de minutos, compatível com o Colab gratuito.
