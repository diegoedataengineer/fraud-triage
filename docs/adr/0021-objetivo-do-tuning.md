# ADR-0021 — Otimizar recall na região de precisão exigida, não PR-AUC

**Status:** Aceita
**Data:** 2026-08-21
**Altera:** [ADR-0004](0004-metrica-primaria.md) (papel da métrica na busca)

## Contexto

A ADR-0004 elegeu PR-AUC como métrica de seleção, e continua certa quanto ao que
descartou: acurácia é inútil com 0,17% de positivos, e ROC-AUC satura. O que não foi
percebido é que **PR-AUC resume a curva inteira**, incluindo regiões de precisão baixa
que a operação jamais usaria.

Isso não é abstrato. O requisito operacional — e o da rubrica — é **precisão ≥ 0,80 com
recall ≥ 0,75**. Otimizar a área sob a curva inteira produz um modelo bom em média e
possivelmente ruim exatamente onde ele vai operar.

Foi o que aconteceu. Com PR-AUC como objetivo, a busca escolheu
`scale_pos_weight ≈ 518`, praticamente o teto do espaço declarado. Ponderação tão
agressiva empurra tudo para recall e destrói a precisão na faixa útil — ótimo para a
área da curva, péssimo para o ponto de operação.

Havia um segundo defeito, de protocolo: a busca otimizava PR-AUC no **split único de
validação**, com apenas 56 positivos. Com 50 tentativas contra um alvo tão pequeno, o
tuning sobreajustou de forma clara — uma execução atingiu **0,8811 na validação e caiu
para 0,6806 no teste**.

## Decisão

O objetivo da busca de hiperparâmetros passa a ser **recall médio na região de precisão
aceitável**, avaliado por **validação cruzada temporal** sobre treino + validação:

```
objetivo = média_folds( max{ recall : precisão ≥ precisão_mínima } )
```

com `precisão_mínima` lida de `config.evaluation.rubric_minimums.precision`, para que o
objetivo do tuning e o requisito de aceitação sejam **o mesmo número**, declarado uma
vez só.

PR-AUC entra como **critério de desempate**, com peso desprezível: entre configurações
que empatam no recall da região útil, prefere-se a de curva melhor no restante. E PR-AUC
segue sendo **reportado** — a ADR-0004 continua valendo para relato e para a comparação
entre modelos ([ADR-0020](0020-criterio-de-adocao.md)).

A validação cruzada, no lugar do split único, é o que remove o sobreajuste de tuning: a
média entre folds é alvo muito mais estável que 56 positivos.

Efeito medido: PR-AUC de teste subiu de **0,7467 para 0,7728**, e o recall médio na
região de precisão ≥ 0,80 chegou a **0,8150** nos folds.

## Alternativas consideradas

- **Manter PR-AUC como objetivo.** Métrica única, simples de explicar e independente de
  limiar. Descartada por desalinhamento: premia regiões da curva que a operação não usa.
- **Otimizar F1.** Diretamente ligado ao ponto de operação. Descartada por embutir a
  premissa de que falso positivo e falso negativo custam o mesmo — falsa neste domínio,
  e contrária à ADR-0010.
- **Restringir o espaço de `scale_pos_weight` à mão.** Resolveria o sintoma observado.
  Descartada por tratar consequência em vez de causa: com o objetivo alinhado, a própria
  busca passa a rejeitar ponderação excessiva.
- **Otimizar precisão a recall fixo.** Espelho da escolha feita. Descartada porque, na
  operação, a precisão é a restrição de capacidade (define o volume de falso positivo
  que a fila aguenta) e o recall é o que se quer maximizar.

## Consequências

- O objetivo do tuning passa a ser o mesmo número que a aceitação exige, eliminando a
  chance de otimizar uma coisa e ser cobrado por outra.
- A busca fica **mais cara**: cada tentativa treina uma vez por fold, não uma vez só. Na
  máquina usada, passou de ~75 s para ~7 min com 50 tentativas — custo aceito.
- O objetivo vira **descontínuo**: quando nenhum limiar atinge a precisão mínima em um
  fold, o valor é zero. Isso cria platôs no espaço de busca e torna o TPE menos
  eficiente. É o preço de otimizar exatamente o que importa.
- PR-AUC deixa de ser a métrica que decide a busca, mas segue reportada — e a distância
  entre as duas leituras vira material de análise no relatório.
