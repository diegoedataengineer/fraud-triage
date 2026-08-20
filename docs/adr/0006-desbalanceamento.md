# ADR-0006 — Tratar o desbalanceamento por ponderação de classe, não por reamostragem sintética

**Status:** Aceita
**Data:** 2026-08-20

## Contexto

A proporção é de 1 fraude para cada 578 transações legítimas. A resposta reflexiva da
literatura é SMOTE, presente em quase todo tutorial deste dataset. Três objeções
concretas pesam contra ele aqui:

1. **As features são componentes de PCA anonimizados.** SMOTE interpola linearmente entre
   vizinhos no espaço de atributos. Sobre variáveis de PCA, os pontos gerados não
   correspondem a nenhuma transação possível — não há restrição de domínio que garanta
   plausibilidade. Estamos inventando fraudes que não existem e afirmando que o modelo
   aprendeu com elas.
2. **É a origem mais comum de vazamento neste dataset.** Aplicar SMOTE antes do split, ou
   dentro da validação cruzada sem encapsular em pipeline, faz cópias sintéticas de
   positivos de treino aparecerem na avaliação. Boa parte dos resultados
   espetaculares publicados sobre esta base vem daí.
3. **Fraude é minoria genuína, não artefato de amostragem.** A raridade é a característica
   definidora do problema. Reequilibrar artificialmente afasta o modelo da distribuição
   sobre a qual ele vai operar, e as probabilidades resultantes deixam de ser
   interpretáveis como risco — o que colide frontalmente com a calibração (ADR-0009).

Algoritmos de gradient boosting já oferecem tratamento nativo por ponderação
(`scale_pos_weight`), que ajusta a contribuição de cada classe na função de perda sem
fabricar observações.

## Decisão

Tratar o desbalanceamento por **ponderação de classe na função de perda**:
`scale_pos_weight` no modelo principal e `class_weight="balanced"` no baseline. **Não**
usar SMOTE, ADASYN, undersampling aleatório nem qualquer reamostragem sintética.

A intensidade da ponderação entra no espaço de busca de hiperparâmetros (ADR-0008) em vez
de ser fixada na razão exata das classes: o valor ótimo sob PR-AUC costuma ser mais
brando que a razão bruta.

Como a ponderação distorce as probabilidades para cima, a calibração da ADR-0009 deixa de
ser refinamento e passa a ser etapa necessária.

## Alternativas consideradas

- **SMOTE aplicado apenas ao treino, dentro de pipeline.** É a forma metodologicamente
  correta de usá-lo e elimina a objeção de vazamento. Descartada pelas objeções 1 e 3, que
  permanecem de pé, e por acrescentar dependência e complexidade sem ganho esperado de
  PR-AUC sobre a ponderação.
- **Undersampling da classe majoritária.** Acelera o treino e equilibra as classes.
  Descartada por descartar a vasta maioria dos dados legítimos, que são justamente o que
  define a fronteira de decisão; perde-se informação sobre o que **não** é fraude.
- **Aprendizado com um classificador de anomalia (Isolation Forest, autoencoder).**
  Adequado quando há pouquíssimos rótulos. Descartada porque temos rótulos, e um
  supervisionado bem ajustado supera consistentemente detecção de anomalia não
  supervisionada nesta base. Fica como referência comparativa no relatório.

## Consequências

- Evitamos a fonte mais comum de resultado inflado neste dataset, ao custo de reportar
  números menos vistosos que boa parte da literatura. É uma escolha de honestidade que
  o relatório deve defender explicitamente.
- As probabilidades saem enviesadas para cima pela ponderação, o que torna a ADR-0009
  obrigatória.
- Uma dependência a menos (`imbalanced-learn`) e um passo a menos onde vazamento poderia
  entrar despercebido.
- Precisamos sustentar tecnicamente a ausência de SMOTE diante de um avaliador que pode
  esperá-lo por convenção. O relatório dedica espaço a isso.
