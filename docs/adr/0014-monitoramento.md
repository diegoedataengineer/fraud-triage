# ADR-0014 — Monitorar com rótulo atrasado, usando drift de distribuição como sinal antecedente

**Status:** Aceita
**Data:** 2026-08-20
**Alterada por:** [ADR-0030](0030-disparo-do-retreino.md) (implementação do disparo)

## Contexto

Propostas de monitoramento de modelos costumam assumir que se pode acompanhar a acurácia
em produção. **Em detecção de fraude, isso é falso**, e essa é a característica que define
o problema operacional.

O rótulo verdadeiro de uma transação não existe no momento da decisão. Ele chega quando o
titular contesta a cobrança — um **chargeback**, que pode levar de dias a meses, com
prazos regulatórios que chegam a 120 dias. Consequências diretas:

- **Recall não é observável em tempo real.** Fraudes não detectadas hoje só se revelarão
  em semanas. Um painel de recall diário estará sempre medindo um passado incompleto.
- **Os rótulos disponíveis são enviesados por seleção.** Transações bloqueadas nunca
  geram chargeback, então não se sabe se eram fraude. O modelo interfere na coleta do
  rótulo que serviria para avaliá-lo.
- **A precisão da faixa de revisão manual é observável rapidamente** — o analista
  produz o rótulo em horas. É o sinal de qualidade mais rápido que temos, e é o que a
  política de três faixas (ADR-0010) torna disponível.

Diante disso, o monitoramento precisa se apoiar em sinais que **antecedem** o rótulo.

## Decisão

Monitoramento em três camadas, ordenadas por latência do sinal:

**1. Imediata — estabilidade de entrada e saída (sem rótulo).**
Drift das features por **PSI** e **teste KS** contra a distribuição de treino, mais a
distribuição dos escores e as frações de aprovação, revisão e bloqueio. Uma queda abrupta
na taxa de encaminhamento à revisão indica mudança de comportamento do modelo ou do
tráfego bem antes de qualquer rótulo chegar. Faixas de alerta usuais para PSI: < 0,1
estável; 0,1–0,25 atenção; > 0,25 drift relevante.

**2. Curta — qualidade da faixa de revisão manual (horas).**
Precisão medida sobre os casos revisados por analistas, e taxa de utilização da
capacidade de revisão. Queda de precisão nessa faixa é o alerta mais rápido de
degradação real.

**3. Longa — desempenho confirmado por chargeback (semanas).**
Recall e custo monetário real, calculados sobre janelas já maduras, com a **data de
maturidade declarada**. Nenhuma métrica de recall é reportada sobre janela imatura sem
rotular como parcial.

Gatilhos de retreino, declarados em configuração: drift relevante em features de alta
importância SHAP, queda da precisão de revisão além de tolerância, ou agenda periódica
como piso — o que ocorrer primeiro.

Como não temos acesso a tráfego de produção, o projeto **demonstra** o mecanismo: mede
drift real entre treino e teste (que são períodos distintos, pela ADR-0003) e simula
cenários de drift induzido para mostrar a resposta dos indicadores.

## Alternativas consideradas

- **Monitorar acurácia/recall em tempo real.** É a proposta convencional. Descartada por
  ser tecnicamente impossível no domínio; apresentá-la demonstraria desconhecimento da
  operação.
- **Somente drift de features.** Simples e sem rótulo. Descartada por insuficiente: drift
  não implica queda de desempenho, e desempenho pode cair sem drift aparente.
- **Retreino em agenda fixa apenas.** Previsível e fácil de operar. Descartada como
  mecanismo único por ser cega: retreina sem necessidade e não reage a mudanças abruptas.
  Mantida como piso de segurança.
- **Ferramenta pronta (Evidently, NannyML).** Reduziria código. Descartada por adicionar
  dependência pesada quando PSI e KS são poucas linhas, e por obscurecer o entendimento
  do mecanismo — que é o que está sendo avaliado.

## Consequências

- A proposta de operacionalização passa a refletir a restrição real do domínio, o que a
  distingue de uma descrição genérica de MLOps.
- Ganhamos um argumento concreto para a política de três faixas: além do benefício
  econômico, a revisão manual **gera rótulos rápidos**, e portanto observabilidade. As
  ADRs 0010 e 0014 se reforçam.
- O relatório precisa explicar o atraso de rótulo antes de apresentar os indicadores, sob
  pena de a ausência de recall em tempo real parecer omissão.
- Assumimos implementar PSI e KS, com o custo de testá-los. Escopo pequeno.
