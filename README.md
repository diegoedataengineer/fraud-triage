# Triagem de Fraude em Transações de Cartão de Crédito

Projeto de Sistematização da disciplina **Engenharia de Aprendizado de Máquina** —
Trilha A (aprendizado supervisionado).

Pipeline completo de detecção de fraude, da ingestão ao monitoramento, com uma
formulação deliberadamente distinta do classificador binário usual: o modelo alimenta
uma **política de triagem em três faixas** — aprovar, revisar manualmente, bloquear —
sujeita à **capacidade real de revisão manual** e construída sobre probabilidades
**explicitamente calibradas**.

## Por que três faixas, e não um limiar

Um classificador binário assume que a única resposta a uma transação suspeita é bloquear
ou liberar. Nenhuma operação antifraude funciona assim: existe uma fila de revisão
manual, ela é o instrumento central da operação, e ela é **finita**.

Essa diferença muda o objeto de otimização. Em vez de escolher um limiar que maximiza
F1 — o que embute a premissa falsa de que um falso positivo custa o mesmo que um falso
negativo —, resolvemos um problema de custo esperado com restrição de capacidade, sobre
probabilidades que significam frequência de fato. E como as premissas de custo são
arbitradas, a conclusão entregue é o **comportamento da política sob variação**, não um
par de números.

Há um segundo benefício, e ele é operacional: a fila de revisão manual **gera rótulos em
horas**, enquanto o rótulo verdadeiro de uma transação só chega semanas depois, via
chargeback. A faixa de revisão é, portanto, a fonte de observabilidade mais rápida do
sistema — e é o que torna o monitoramento viável.

Decisões completas em [`docs/adr/0010`](docs/adr/0010-politica-de-decisao.md) e
[`docs/adr/0014`](docs/adr/0014-monitoramento.md).

## Dataset

Credit Card Fraud Detection (MLG-ULB), obtido do **OpenML** (data id 1597) por download
direto do ARFF — sem autenticação, sem caminho local.

| | |
|---|---|
| Transações | 284.807 |
| Features | 31 (`Time`, `V1`–`V28` de PCA, `Amount`, `Class`) |
| Fraudes | 492 (**0,1727%**) |
| Janela | 48 horas contíguas |
| Nulos | 0 |

O `fetch_openml` do scikit-learn **descarta a coluna `Time`** (o OpenML a marca como
atributo ignorado), o que inviabilizaria o particionamento cronológico. Daí o download do
ARFF bruto — ver [`docs/adr/0002`](docs/adr/0002-fonte-de-dados.md).

## Estrutura

```
config/config.yaml      configuração central — nada fixo em código
src/                    o pipeline real (fonte da verdade)
  ingestion.py            download do ARFF, parsing e validação da fonte
  eda.py                  análise exploratória
  preprocessing.py        split cronológico, atributos derivados, escalonamento
  train.py                baseline + XGBoost com Optuna
  calibration.py          isotônica vs. Platt, Brier e ECE
  evaluate.py             métricas, validação cruzada temporal, figuras
  policy.py               política de três faixas e análise de sensibilidade
  explainability.py       SHAP global, local e operacional
  utils.py                config, logging, sementes
monitoring/drift_monitor.py    PSI, KS, camadas e gatilhos
deploy/                 demonstração com Faker, API de inferência, benchmark
notebooks/              notebook do Colab — importa de src/, não reimplementa
reports/                relatório, figuras e artefatos JSON de cada execução
tests/                  testes dos invariantes
docs/adr/               14 registros de decisão — o porquê
docs/specs/             6 especificações — o quê e como verificar
run_pipeline.py         entry point único
```

## Documentação

Antes de mexer no código, vale ler nesta ordem:

- [`docs/PLANO.md`](docs/PLANO.md) — sequência de execução, riscos e estado
- [`docs/adr/`](docs/adr/) — por que cada decisão foi tomada
- [`docs/specs/`](docs/specs/) — o que construir e como verificar
- [`docs/RUBRICA.md`](docs/RUBRICA.md) — onde cada ponto avaliado é atendido

## Como executar

Requer Python 3.10+ (testado em 3.10 a 3.12).

```bash
pip install -r requirements.txt
python run_pipeline.py
```

Cada etapa também roda isolada:

```bash
python -m src.ingestion
python -m src.preprocessing
python -m src.train
```

## Princípios que o código respeita

Não são estilo, são correção — cada um tem teste automatizado:

1. **Particionamento cronológico.** Fraude é adversarial e não estacionária; embaralhar
   vaza o futuro e produz métrica que não se realiza em produção.
2. **O teste é tocado uma única vez.** Escalonador, calibrador e limiares saem do treino
   ou da validação, nunca do teste.
3. **Sem SMOTE.** Interpolar sobre componentes de PCA fabrica transações impossíveis. O
   desbalanceamento é tratado por ponderação de classe.
4. **Métricas da classe positiva.** Com 0,17% de positivos, média ponderada passa de 0,99
   sem informar nada.
5. **Todo número vem de execução real**, gravado em `reports/*.json` — inclusive os
   desfavoráveis.

## Limitações declaradas

- `V1`–`V28` são componentes de PCA anonimizados: **não há** interpretação de negócio
  possível para elas. Apenas `Amount` e `Hour` são semanticamente legíveis, e o relatório
  restringe a leitura a esses.
- As premissas de custo da política são arbitradas — daí a análise de sensibilidade.
- As transações sintéticas da demonstração não preservam a correlação entre componentes:
  servem para exercitar o caminho de inferência, não para medir desempenho.
- 48 horas de dados não sustentam validação por janela deslizante com positivos
  suficientes.

---

Diego Nunes de Morais
