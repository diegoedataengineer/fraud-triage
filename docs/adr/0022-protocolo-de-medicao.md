# ADR-0022 — Medir ranking sobre escore bruto e escolher limiares fora-de-fold

**Status:** Aceita
**Data:** 2026-08-21
**Altera:** [ADR-0009](0009-calibracao.md) (invariante de calibração) ·
[ADR-0010](0010-politica-de-decisao.md) (origem do ponto de operação)

## Contexto

Três defeitos de protocolo apareceram durante a implementação. Nenhum era erro de código:
os três eram formulações plausíveis e erradas, e cada um produzia números enganosos sem
quebrar nada.

**1. Ranking medido sobre escore calibrado.** A ADR-0009 afirmou que a calibração, sendo
monotônica, não poderia alterar PR-AUC nem ROC-AUC, e a Spec 002 transformou isso em
critério de aceite com tolerância de 1e-6. A afirmação é falsa. A regressão isotônica é
monotônica **não decrescente**, mas não estritamente: ela colapsa faixas inteiras de
escore no mesmo valor, e os empates resultantes deslocam métricas de ordenação. Medido:
o ROC-AUC do XGBoost caiu de **0,9802 para 0,9472** apenas por ser calculado sobre o
escore calibrado — uma reprovação no mínimo da rubrica causada por artefato de medição,
não por piora do modelo.

**2. Verificação de monotonicidade em precisão insuficiente.** O `predict_proba` do
XGBoost devolve **float32**. A isotônica ajustada sobre float32 emite valores do mesmo
platô diferindo em **2,3e-10** — exatamente **um ULP** naquela magnitude. Uma checagem
com tolerância fixa de 1e-12 acusava violação de monotonicidade onde havia apenas
arredondamento.

**3. Limiar escolhido sobre a validação isolada.** Com **56 positivos**, a precisão
estimada na validação tem incerteza de vários pontos percentuais. Um limiar escolhido ali
não transferiu: precisão de ~0,81 na validação virou **0,7358** no teste. Exigir
intervalo de confiança de 95% sobre esse conjunto foi pior ainda — nenhum limiar
permanecia viável.

## Decisão

**Ranking sobre escore bruto.** PR-AUC e ROC-AUC passam a ser calculados sobre a saída
não calibrada. São métricas de **ordenação**, e a calibração existe para dar significado
de frequência à escala — não para melhorar ordenação. Brier, ECE e as decisões de faixa
continuam sobre o escore calibrado, que é onde a escala importa.

**Invariante de calibração reformulado.** Em vez de exigir imutabilidade das métricas,
verifica-se o que de fato precisa ser verdade:

- o mapeamento é **monotônico não decrescente**, checado de forma exata sobre os escores
  ordenados, com tolerância derivada de `np.finfo(dtype).eps` e da escala dos valores —
  não de uma constante arbitrária;
- a degradação de ranking não excede `config.calibration.max_ranking_degradation`, o que
  detecta empates em excesso sem reprovar arredondamento legítimo.

Os escores são convertidos para **float64 na origem**, antes de calibrar. Calibração é
ajuste numérico; não há razão para fazê-la em meia precisão.

**Limiar escolhido sobre predições fora-de-fold.** O ponto de operação passa a ser
determinado sobre as predições *out-of-fold* da validação cruzada — cada linha prevista
por um modelo que não a viu no treino. São **~422 positivos** em vez de 56, e nenhuma
linha de teste participa. É a diferença entre um limiar estável e um que não transfere.

Fica explícita, também, a separação entre **ponto de operação** e **política de três
faixas**: são respostas a perguntas diferentes. A rubrica avalia um classificador
binário; a política descreve como a operação usa o escore. Ambos são reportados, e
nenhum é apresentado como se fosse o outro.

## Alternativas consideradas

- **Calcular ranking sobre o escore calibrado assim mesmo.** Um único escore em todo o
  relatório, mais simples de narrar. Descartada por produzir número falsamente pior, e
  por confundir duas propriedades distintas: ordenar bem e estimar frequência.
- **Escolher Platt no lugar da isotônica para evitar empates.** Estritamente monotônica,
  resolveria o artefato. Descartada porque a isotônica venceu no Brier, e trocar a
  calibração para contornar um problema de **medição** seria consertar a coisa errada.
- **Margem fixa sobre a precisão-alvo na validação.** Simples de implementar.
  Descartada por arbitrária: o tamanho da margem seria escolhido olhando o resultado,
  que é vazamento por tentativa.
- **Intervalo de Wilson a 95% sobre a validação.** Estatisticamente principiado.
  Descartada por, na prática, não deixar nenhum limiar viável com 56 positivos — a
  incerteza é grande demais para esse conjunto sustentar a decisão. A resposta certa era
  usar **mais dados**, não uma exigência mais dura sobre dados insuficientes.

## Consequências

- Os números do relatório passam a medir o que dizem medir. O ROC-AUC do modelo adotado
  é **0,9802**, acima do mínimo — e não os 0,9472 que o protocolo anterior produzia.
- O limiar do ponto de operação ganha base amostral quase oito vezes maior.
- O relatório carrega três leituras (bruto para ordenação, calibrado para escala, faixas
  para operação) e precisa dizer claramente qual responde a quê, sob pena de confundir.
- Registra-se que os três defeitos eram de **formulação**, não de implementação: o código
  fazia exatamente o que fora especificado. É argumento a favor de verificar
  especificações contra dados reais cedo, e não apenas revisá-las no papel.
