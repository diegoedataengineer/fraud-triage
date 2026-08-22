# ADR-0010 — Definir o corte como política de triagem em três faixas, com restrição de capacidade

**Status:** Aceita
**Data:** 2026-08-20
**Alterada por:** [ADR-0022](0022-protocolo-de-medicao.md) (origem do ponto de operação) ·
[ADR-0024](0024-piso-de-perda-por-fraude.md) (modelo de custo) ·
[ADR-0025](0025-grade-de-limiares.md) (busca dos limiares) ·
[ADR-0026](0026-reajuste-em-treino-mais-validacao.md) (conjunto de otimização) ·
[ADR-0028](0028-calibracao-do-artefato.md) (a faixa intermediária dependia da escala calibrada)

## Contexto

Um classificador binário com limiar único assume que a única resposta possível a uma
transação suspeita é **bloquear ou liberar**. Nenhuma operação antifraude funciona assim.
A resposta real tem pelo menos três formas, com custos muito diferentes:

- **Liberar** — custo zero se legítima; perda integral do valor se for fraude.
- **Encaminhar para revisão manual** — custo do analista, mais atrito com o cliente. É um
  recurso **limitado**: existe um número finito de revisões por dia.
- **Bloquear automaticamente** — evita a perda se for fraude; se for engano, gera atrito
  severo, risco de perda do cliente e custo de atendimento.

Os custos são também assimétricos entre si. Deixar passar uma fraude custa o valor da
transação; bloquear uma transação legítima custa atrito e suporte. Tratá-los como iguais
— que é o que otimizar F1 ou acurácia faz implicitamente — é uma premissa econômica
errada, apenas não declarada.

A restrição de capacidade é o que torna o problema interessante: não adianta a política
mandar 5% das transações para revisão se a equipe consegue revisar 0,5%.

## Decisão

Substituir o limiar binário por uma **política de triagem em três faixas**, definida
sobre a probabilidade **calibrada** (ADR-0009):

```
p < t_baixo              →  aprovar automaticamente
t_baixo ≤ p < t_alto     →  encaminhar para revisão manual
p ≥ t_alto               →  bloquear automaticamente
```

Os dois limiares são obtidos **na partição de validação**, resolvendo um problema de
otimização explícito:

- **Objetivo:** minimizar o custo total esperado, com os custos declarados em
  `config/config.yaml` — perda por fraude não detectada proporcional ao `Amount` da
  transação, custo fixo por revisão manual e custo fixo por bloqueio indevido.
- **Restrição:** a fração encaminhada à revisão manual não pode exceder a **capacidade
  operacional** declarada em configuração (parâmetro em % do volume diário).

Como as premissas de custo são arbitradas, elas não podem ser tratadas como verdade. O
projeto entrega junto uma **análise de sensibilidade**: como os limiares e o custo total
se deslocam quando a razão entre custos e a capacidade de revisão variam. A conclusão
robusta não é um par de números, é o comportamento da política.

Para atender à rubrica, reportamos **também** as métricas de um **ponto de operação
binário**, que é objeto distinto da política.

> **Precisado pela [ADR-0022](0022-protocolo-de-medicao.md):** tratar "tudo acima de
> `t_baixo`" como positivo não serve, porque `t_baixo` é o limiar de *encaminhamento à
> revisão* — uma faixa deliberadamente generosa, cuja precisão é baixa por construção. A
> rubrica avalia um classificador binário; a política descreve a operação. São perguntas
> diferentes e passam a ser reportadas separadamente. O limiar do ponto de operação é
> escolhido sobre as **predições fora-de-fold** (~422 positivos), não sobre a validação
> isolada (56 positivos), onde não transferia para o teste.

## Alternativas consideradas

- **Limiar único em 0,5.** Padrão implícito de qualquer `.predict()`. Descartado por ser
  arbitrário: 0,5 não tem significado sob desbalanceamento extremo e ponderação de classe.
- **Limiar único otimizando F1.** Comum e simples de justificar. Descartado por assumir
  custos simétricos entre falso positivo e falso negativo, premissa falsa neste domínio.
- **Limiar único por custo esperado.** Já é bom e é o que a referência do professor faz.
  Descartado como formulação final por manter a limitação binária: descarta a revisão
  manual, que é o instrumento central de uma operação antifraude real.
- **Otimizar a política diretamente no teste.** Daria os melhores números. **Rejeitado
  por ser vazamento** — o teste é tocado uma única vez, para reportar.

## Consequências

- O projeto passa a ter formulação própria, distinta da referência pública do mesmo
  domínio, atendendo à preocupação levantada na ADR-0001.
- A rubrica de operacionalização (3 pontos) ganha sustentação concreta: a política liga o
  modelo a uma restrição operacional real, em vez de descrever monitoramento em abstrato.
- Aumenta a complexidade de avaliação: passamos a reportar métricas por faixa, não apenas
  uma matriz de confusão 2×2. Exige mais cuidado de apresentação no relatório.
- As premissas de custo são arbitradas e podem ser questionadas. A análise de
  sensibilidade existe para que a conclusão não dependa delas.
- Dependemos da qualidade da calibração. Se ela falhar, as faixas perdem sentido — motivo
  pelo qual a ADR-0009 exige medição explícita, e não apenas execução.
