# Spec 006 — Demonstração funcional, notebook e entrega

**ADRs relacionadas:** [0012](../adr/0012-fonte-da-verdade.md) ·
[0013](../adr/0013-reprodutibilidade.md)

## `deploy/demo_faker.py` — demonstração com dados novos

O enunciado exige demonstração funcional executando previsões sobre **novos dados**, e
sugere `faker`.

### Comportamento

1. Gerar `N` transações sintéticas com `Faker` (semente fixa), no **mesmo formato** dos
   dados reais: `Time`, `V1`–`V28`, `Amount`.
2. Amostrar `V1`–`V28` de distribuições ajustadas às marginais **do treino**, e `Amount`
   de uma log-normal calibrada pela distribuição real.
3. Aplicar **exatamente** o mesmo pré-processamento do treino — reusando os objetos
   persistidos, jamais reajustando.
4. Executar modelo + calibrador e aplicar a política de três faixas (Spec 003).
5. Exibir, por transação: valor, probabilidade calibrada, faixa (aprovar / revisar /
   bloquear) e os principais fatores SHAP.

### Limitação a declarar

Transações geradas a partir de marginais independentes **não preservam a estrutura de
correlação** entre as componentes de PCA. Servem para demonstrar o caminho de inferência
ponta a ponta, **não** para avaliar desempenho. O relatório declara isso; medir métricas
sobre dados sintéticos seria inválido.

Para complementar, a demonstração inclui também transações reais retiradas do teste,
onde o rótulo é conhecido e a previsão é verificável.

## `deploy/api.py` — serviço de inferência

FastAPI com contrato mínimo:

| Rota | Função |
|---|---|
| `GET /health` | estado do serviço e versão do modelo |
| `POST /predict` | recebe transação, devolve probabilidade calibrada, faixa e fatores |

Entrada e saída validadas por Pydantic. O modelo é carregado uma vez na inicialização,
nunca por requisição. `deploy/benchmark_latency.py` mede latência p50/p95/p99 e vazão —
números medidos, jamais estimados.

## `notebooks/` — o notebook do Colab

Fonte da verdade é `src/` (ADR-0012). O notebook clona o repositório em um **commit ou
tag fixo**, instala as dependências travadas e narra a execução.

### Estrutura, espelhando os entregáveis exigidos

1. Setup (clone em ref fixo, instalação, sementes)
2. Ingestão e validação da fonte
3. Análise exploratória
4. Pré-processamento e particionamento cronológico
5. Baseline e modelo principal
6. Calibração
7. Avaliação e verificação das métricas mínimas
8. Política de três faixas e sensibilidade
9. Explicabilidade
10. Demonstração com dados novos
11. Monitoramento e drift
12. Conclusões

### Critérios de aceite

- Executa do início ao fim, do zero, **sem alterações** — validado por execução limpa.
- Nenhum caminho local, nenhuma credencial, nenhuma entrada interativa.
- Os números exibidos coincidem com os de `reports/*.json`.
- Tempo total compatível com uma sessão do Colab gratuito.
- Compartilhado em modo de visualização antes da entrega.

## `reports/relatorio.md` — o relatório

Segue exatamente a estrutura exigida: Capa · Introdução · Descrição do problema ·
Dataset utilizado · Metodologia · Pipeline de ML · Resultados experimentais · Análise das
métricas · Explicabilidade · Estratégia de monitoramento · Conclusão.

**Todo número no relatório vem de um arquivo em `reports/*.json` gerado por execução
real.** Nenhum valor é digitado à mão ou estimado — inclusive os desfavoráveis.

Seção obrigatória de **achados honestos**: gap de generalização, limitações do PCA,
premissas de custo arbitradas, limitação dos dados sintéticos e o que não foi feito.
Análise crítica é o que a rubrica premia; omitir limitação é o erro mais caro.

## Montagem do PDF final

Documento único, na ordem: relatório completo → notebook executado exportado em PDF →
link do Colab (visualização) → link do vídeo de apresentação.

### Checklist de entrega

- [ ] Notebook executa integralmente, do zero, sem alterações
- [ ] Métricas mínimas atingidas no teste: AUC-ROC ≥ 0,95 · Recall ≥ 0,75 · Precision ≥ 0,80
- [ ] Números do relatório conferem com `reports/*.json`
- [ ] Colab compartilhado em modo de visualização
- [ ] Vídeo hospedado em plataforma de livre acesso
- [ ] Repositório público no ref citado pelo notebook
- [ ] Nenhuma marca de ferramenta de IA em texto, código, commits ou metadados do PDF
