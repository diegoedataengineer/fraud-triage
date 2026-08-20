# Plano de execução

**Prazo:** 23/08/2026 23:55 · **Documentação concluída em:** 20/08/2026

A documentação (ADRs e specs) está fechada. O que segue é implementação, e a ordem
importa: cada fase depende dos artefatos da anterior.

## Estado

| Fase | Entrega | Estado |
|---|---|---|
| 0 | Decisões, ADRs, specs, configuração, esqueleto | **Concluída** |
| 1 | Ingestão validada + EDA | Pendente |
| 2 | Pré-processamento e particionamento cronológico | Pendente |
| 3 | Baseline + XGBoost/Optuna + calibração | Pendente |
| 4 | Avaliação, política de três faixas, sensibilidade | Pendente |
| 5 | Explicabilidade (SHAP) | Pendente |
| 6 | Monitoramento e drift | Pendente |
| 7 | Demonstração (Faker + API) | Pendente |
| 8 | Notebook do Colab | Pendente |
| 9 | Relatório e montagem do PDF | Pendente |
| 10 | Vídeo de apresentação | Pendente |

## Sequência

**Fase 1 — Fundação de dados.** `src/utils.py` (carga de config, logging, sementes),
`src/ingestion.py` com a validação da Spec 001, `src/eda.py`. Ao fim, o cache Parquet
existe e as figuras de EDA estão geradas.
*Porta de saída:* a validação de ingestão passa nos dez critérios.

**Fase 2 — Preparação.** `src/preprocessing.py`: ordenação, split 70/15/15 cronológico,
dedup no treino, três atributos derivados, `RobustScaler` ajustado só no treino.
*Porta de saída:* teste automatizado prova que não há sobreposição de índices, que os
cortes temporais são estritos e que cada partição tem ao menos um positivo.

**Fase 3 — Modelagem.** Baseline, depois XGBoost com Optuna, depois calibração.
*Porta de saída:* o critério de adoção da Spec 002 foi aplicado; o invariante de
ranking da calibração passa.

**Fase 4 — Avaliação e política.** Métricas no teste (tocado uma vez), otimização dos
limiares na validação sob restrição de capacidade, análise de sensibilidade.
*Porta de saída:* **as métricas mínimas da rubrica são atingidas.** Este é o ponto de
maior risco do cronograma — se falhar, tudo depois espera.

**Fase 5 a 7 — Explicabilidade, monitoramento, demonstração.** Independentes entre si;
podem ser feitas em qualquer ordem depois da Fase 4.

**Fase 8 — Notebook.** Só depois que `src/` estiver estável: o notebook narra a execução,
e narrar código instável gera retrabalho.
*Porta de saída:* execução limpa, do zero, sem alterações.

**Fase 9 — Relatório.** Escrito por último, com todos os números já em `reports/*.json`.
Escrever antes convida a estimar valores, o que viola o invariante 5 do `CONTEXTO.md`.

**Fase 10 — Vídeo.** Depende do relatório pronto.

## Riscos e mitigação

| Risco | Impacto | Mitigação |
|---|---|---|
| Métricas mínimas não atingidas | 7 pontos | Trilha escolhida por folga de métrica (ADR-0001); ponto de decisão explícito na Fase 4 |
| Calibração isotônica sobreajusta com ~74 positivos na validação | política sem sentido | Comparação obrigatória com Platt, escolha por Brier (ADR-0009) |
| OpenML indisponível na correção | notebook não roda | Cache em Parquet; validação falha de forma explícita; fonte pública reconhecida |
| Repositório privado no momento da correção | notebook não clona | Publicar com antecedência e fixar tag; item do checklist |
| Colab altera imagem base | divergência de métricas | Versões travadas; versão de Python testada declarada no README |
| Prazo curto para o vídeo | 5 pontos do critério 7 | Relatório fechado até a Fase 9; vídeo é roteiro do relatório |

## Ordem de sacrifício

Se o tempo apertar, corta-se de baixo para cima — nunca o inverso:

1. `deploy/api.py` e benchmark de latência (não estão na rubrica)
2. Análise de sensibilidade estendida (mantendo ao menos três níveis)
3. Explicação SHAP operacional (mantendo global e local)

**Nada acima disso é sacrificável**: cada item restante sustenta um critério pontuado.
