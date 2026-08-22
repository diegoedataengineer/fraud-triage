# ADR-0023 — Travar os hiperparâmetros vencedores em arquivo versionado

**Status:** Aceita
**Data:** 2026-08-22
**Complementa:** [ADR-0013](0013-reprodutibilidade.md) · [ADR-0015](0015-esteira-de-promocao.md)

## Contexto

A ADR-0013 tratou três fontes de variação — aleatoriedade, versões de biblioteca e
ambiente — e cobriu as três. Uma quarta passou despercebida, e só apareceu ao comparar
duas execuções completas do pipeline.

O `XGBoost` com `n_jobs=-1` soma gradientes em paralelo, e soma de ponto flutuante não é
associativa: a ordem de redução varia entre execuções e o resultado muda nos últimos
bits. Isso, por si, seria irrelevante. O problema é o efeito em cascata: a variação
altera o valor do objetivo, o valor altera as decisões do amostrador TPE, e as decisões
alteram toda a trajetória da busca.

O resultado medido não foi uma diferença marginal. Duas execuções produziram **modelos
substancialmente distintos** — `scale_pos_weight` de 518 contra 15,9, `max_depth` de 3
contra 9 — com desempenho praticamente idêntico em validação cruzada (0,8262 contra
0,8263). O objetivo tem um **platô**: muitas configurações diferentes pontuam igual, e a
busca escolhe qualquer uma delas.

O efeito nas métricas reportadas foi visível: a precisão no teste oscilou entre 0,7358 e
0,7500 — uma transação mudando de lado na fronteira de decisão.

Isso é tolerável para explorar e inaceitável para um artefato que será **reexecutado e
conferido**, com divergência de métricas sujeita a desconto de nota.

## Decisão

Separar **busca** de **reprodução**, gravando os hiperparâmetros vencedores em
`config/model_params.lock.json`, versionado junto ao código.

- Quando o arquivo existe, a busca é **ignorada** e o modelo é reconstruído exatamente a
  partir dos parâmetros travados.
- Uma busca nova é explícita: `HPO_FORCE_SEARCH=1`, que reescreve o arquivo ao final.

É a aplicação do princípio que a ADR-0015 já defende para a esteira — **o que se promove
é o artefato, não o processo que o gerou**. A busca de hiperparâmetros é exploração; o
modelo escolhido é o produto. Reexecutar a exploração e esperar o mesmo resultado
confunde as duas coisas.

Efeito verificado: duas execuções consecutivas produziram métricas **idênticas até a
décima casa decimal**, incluindo a matriz de confusão. Como efeito secundário, o pipeline
caiu de ~16 minutos para ~1 minuto, o que torna a reexecução barata para quem avalia.

## Alternativas consideradas

- **`n_jobs=1` no XGBoost.** Elimina o não determinismo na origem. Descartada pelo custo:
  a busca passaria de 16 minutos para mais de uma hora, e o problema de fundo — o platô
  do objetivo — continuaria fazendo a busca escolher configurações arbitrárias entre
  equivalentes.
- **Fixar `n_jobs` em um número em vez de `-1`.** Reduz a variação. Descartada por não
  eliminá-la: o resultado continuaria dependendo do número de núcleos da máquina, e a
  máquina de quem avalia não é a nossa.
- **Aceitar a variação e reportar faixas em vez de valores.** Honesto e defensável.
  Descartada porque a rubrica compara números pontuais, e uma faixa seria lida como
  imprecisão em vez de rigor.
- **Escrever os parâmetros direto no `config.yaml`.** Menos um arquivo. Descartada para
  manter separado o que é **decisão humana** (a configuração) do que é **resultado de
  busca** (o lock) — misturá-los tornaria o diff da configuração ilegível a cada
  retreino.

## Consequências

- As métricas do relatório são reproduzíveis por qualquer pessoa, em qualquer máquina.
- A reexecução fica ~16× mais rápida, o que reduz o atrito de quem for conferir.
- Surge a obrigação de **manter o lock coerente com o modelo publicado**: um lock
  desatualizado reconstruiria um modelo diferente do artefato. A esteira não o regenera
  sozinha, por decisão — regenerar automaticamente reintroduziria a variação.
- O platô do objetivo fica documentado como achado: neste problema, muitas configurações
  distintas de gradient boosting alcançam desempenho equivalente, e a escolha entre elas
  é arbitrária dentro do ruído.
