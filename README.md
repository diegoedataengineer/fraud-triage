# Triagem de Fraude em Transações de Cartão de Crédito

Projeto de Sistematização da disciplina **Engenharia de Aprendizado de Máquina** —
Trilha A (aprendizado supervisionado).

Pipeline completo de detecção de fraude, da ingestão ao monitoramento, com uma
formulação deliberadamente distinta do classificador binário usual: o modelo alimenta
uma **política de triagem em três faixas** — aprovar, revisar manualmente, bloquear —
sujeita à **capacidade real de revisão manual** e construída sobre probabilidades
**explicitamente calibradas**.

```bash
docker run -p 8000:8000 diegodataengineer/fraud-triage:1.4.1
```

Swagger interativo em `http://localhost:8000/docs`.

> **Versão de entrega: `1.4.1`.** É a versão avaliada, fixada no `docker-compose.yml` e
> referenciada em toda a documentação. Foi promovida pela esteira por *retag* do digest
> validado em homologação — a imagem em produção é, byte a byte, a que passou pela
> verificação, sem reconstrução ([ADR-0019](docs/adr/0019-registry-de-imagens.md)).
>
> Um detalhe que costuma confundir: `/health` responde `model_version: "1.3.0"`, e não
> `1.4.1`, e o console mostra os dois lado a lado. Está correto. O artefato é carimbado com a versão **no momento do build em
> homologação** — commit `57e7f58` —, enquanto o número da release só é atribuído **na
> promoção**. E promover é retag, não reconstrução: renumerar o que está dentro exigiria
> construir de novo, produzindo uma imagem diferente da que foi validada. O elo
> confiável entre as duas é o `git_sha` gravado no metadata.
>
> Para fixar outra versão sem editar o compose: `FRAUD_TAG=1.4.1 docker compose up`.

---

## Índice

- [Começando do zero](#começando-do-zero) — clonar, instalar, treinar, testar
- [O ecossistema completo](#o-ecossistema-completo) — console, API e banco
- [Testes e verificação](#testes-e-verificação)
- [Testar a API](#testar-a-api) — Postman e `curl`
- [Por que três faixas](#por-que-três-faixas-e-não-um-limiar)
- [Resultados](#resultados)
- [Guia da documentação](#guia-da-documentação) — 27 ADRs e 7 especificações
- [Estrutura do repositório](#estrutura-do-repositório)
- [Princípios que o código respeita](#princípios-que-o-código-respeita)
- [Limitações declaradas](#limitações-declaradas)

---

## Começando do zero

### Pré-requisitos

| | |
|---|---|
| Python | 3.10 a 3.12 (testado em 3.11) |
| Docker | opcional, para o ecossistema completo |
| Rede | a ingestão baixa 150 MB do OpenML na primeira execução |

Não é preciso conta em nuvem, credencial nem chave de API. A base é pública e a
ingestão dispensa autenticação.

### 1. Clonar e preparar o ambiente

```bash
git clone https://github.com/diegoedataengineer/fraud-triage
cd fraud-triage

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

As versões são **fixadas**, não faixas. A razão está na
[ADR-0013](docs/adr/0013-reprodutibilidade.md): o projeto é reexecutado em data futura, e
qualquer resolução por faixa pode instalar uma versão incompatível nesse intervalo.

### 2. Rodar os testes

```bash
pytest
```

São 20 testes dos **invariantes** do pipeline — não de estilo, de correção. Cada um cobre
uma forma conhecida de vazamento: sobreposição temporal entre partições, partição sem
positivo, escalonador ajustado fora do treino, `Time` vazando como atributo, e cada
critério de validação da fonte. Levam menos de um segundo, porque usam dados sintéticos.

### 3. Executar o pipeline completo

```bash
python run_pipeline.py
```

Executa ingestão, validação da fonte, preparação, treino, calibração, política,
avaliação, explicabilidade e monitoramento, e grava o artefato versionado.

Leva **cerca de dois minutos**, mais o download de 150 MB na primeira vez — os
hiperparâmetros estão travados em `config/model_params.lock.json`
([ADR-0023](docs/adr/0023-hiperparametros-travados.md)), então a busca é pulada e o
resultado é idêntico a cada execução, até a décima casa decimal.

Para refazer a busca do zero — cerca de 16 minutos:

```bash
HPO_FORCE_SEARCH=1 python run_pipeline.py
```

O que fica ao final:

```
models/fraud-triage/1.1.0/    modelo, calibrador, política e metadata.json
reports/*.json               métricas de cada etapa
reports/figures/*.png        15 figuras
```

### 4. Ver o modelo decidindo

```bash
python -m deploy.demo_faker
```

Mostra transações sintéticas percorrendo a inferência e, em seguida, transações **reais
do conjunto de teste**, com rótulo conhecido — nessas dá para conferir se a decisão está
certa.

### 5. Subir a API sozinha

```bash
python -m deploy.api
```

Sem `DATABASE_URL` ela responde inferência normalmente e não persiste
([ADR-0018](docs/adr/0018-persistencia-operacional.md)).

---

## O ecossistema completo

```bash
docker compose up
```

| Serviço | Papel | Endereço |
|---|---|---|
| `console` | painel de operação e demonstração | http://localhost:3100 |
| `api` | inferência, política e fila de revisão | http://localhost:8000/docs |
| `db` | estado operacional em PostgreSQL | porta 5432 |

Funciona **a partir de um clone limpo**: o compose usa as imagens publicadas, sem exigir
build local. O artefato do modelo não é versionado — ele é reconstruído pelo pipeline —,
então construir a imagem antes de rodar `run_pipeline.py` produziria uma imagem sem
modelo.

Para construir a partir do código local, depois de rodar o pipeline:

```bash
python run_pipeline.py
docker compose -f docker-compose.yml -f docker-compose.build.yml up --build
```

### O que fazer no console

Abra `http://localhost:3100` e:

1. **Enviar transação** — uma transação real do teste percorre o diagrama na tela,
   enquanto o inspetor mostra o comando enviado e a resposta de cada etapa, com o tempo.
2. **Fraude conhecida** — envia uma fraude confirmada. *Parte delas será aprovada*: é o
   recall de 0,75 aparecendo ao vivo.
3. **Caso de fronteira** — busca uma transação que caia na faixa de revisão, que captura
   0,03% do volume e sem busca dirigida quase nunca aparece.
4. **Clicar numa decisão** — abre o rastro completo daquela transação, com o custo de
   cada etapa em barra proporcional.
5. **Dar veredito na fila** — alimenta a camada 2 do monitoramento, visível em
   `/monitoring/review-precision`.

---

## Testes e verificação

```bash
pytest                                  # 20 invariantes do pipeline
pytest -v                               # com o nome de cada teste

python -m src.ingestion                 # baixa e valida a fonte (10 critérios)
python -m src.eda                       # análise exploratória e 4 figuras
python -m src.preprocessing             # particionamento e atributos
python -m src.verify_minimums           # porta de qualidade da rubrica
```

Conferir que dois pipelines seguidos dão o mesmo resultado:

```bash
python run_pipeline.py && cp reports/evaluation_summary.json /tmp/a.json
python run_pipeline.py && diff <(jq .models /tmp/a.json) <(jq .models reports/evaluation_summary.json) \
  && echo "reprodutível"
```

Exercitar a API:

```bash
curl http://localhost:8000/health
curl "http://localhost:8000/simulate/sample?kind=fraud"
curl -X POST "http://localhost:8000/predict?trace=true" \
  -H 'Content-Type: application/json' -d @transacao.json
```

O `?trace=true` devolve os valores intermediários de cada etapa, com o tempo gasto —
features geradas, escore bruto, transformação da calibração e a comparação exata que
define a faixa.

---

## Testar a API

Uma coleção do Postman pronta, com payloads reais, está em
[`postman/fraud-triage.postman_collection.json`](postman/fraud-triage.postman_collection.json)
— importe e as 11 requisições já funcionam contra `http://localhost:8000`.

A referência completa dos endpoints, com exemplos em `curl` e um roteiro de teste em cinco
passos, está em [`docs/API.md`](docs/API.md).

---

## Por que três faixas, e não um limiar

Um classificador binário assume que a única resposta a uma transação suspeita é bloquear
ou liberar. Nenhuma operação antifraude funciona assim: existe uma fila de revisão
manual, ela é o instrumento central da operação, e ela é **finita**.

Isso muda o objeto de otimização. Em vez de escolher um limiar que maximiza F1 — o que
embute a premissa falsa de que um falso positivo custa o mesmo que um falso negativo —,
resolvemos um problema de custo esperado com restrição de capacidade, sobre
probabilidades que significam frequência de fato.

Há um segundo benefício, operacional: a fila de revisão **gera rótulos em horas**,
enquanto o rótulo verdadeiro só chega semanas depois via chargeback. Ela é a fonte de
observabilidade mais rápida do sistema — e é o que torna o monitoramento viável.

Ver [ADR-0010](docs/adr/0010-politica-de-decisao.md) e
[ADR-0014](docs/adr/0014-monitoramento.md).

---

## Resultados

| Métrica | Obtido | Mínimo | |
|---|---|---|---|
| ROC-AUC | **0,9856** | 0,95 | ✅ |
| Recall | **0,7500** | 0,75 | ✅ |
| Precisão | **0,7800** | 0,80 | ❌ |
| PR-AUC | 0,7697 | — | |
| Brier / ECE | 0,000425 / 0,000054 | — | |

A precisão fica a **duas transações** do mínimo: são 11 falsos positivos onde seriam
necessários no máximo 9. Com 52 fraudes no teste, cada uma vale 1,92 ponto de recall — a
métrica se move em degraus grossos.

A causa está em duas decisões deliberadas: **particionamento cronológico**
([ADR-0003](docs/adr/0003-split-temporal.md)) e **ausência de reamostragem sintética**
([ADR-0006](docs/adr/0006-desbalanceamento.md)). Com split aleatório e SMOTE os mínimos
seriam atingidos com folga — e os números não corresponderiam ao desempenho realizável.

Análise completa em [`reports/relatorio.md`](reports/relatorio.md) e no
[PDF](reports/relatorio.pdf).

---

## Guia da documentação

O **porquê** de cada decisão está nas ADRs; o **quê construir e como verificar**, nas
especificações. Elas não repetem o código — registram o raciocínio que se perde primeiro.

### Por onde começar

| Documento | Para quê |
|---|---|
| [`docs/CONTEXTO.md`](docs/CONTEXTO.md) | orientação para quem vai trabalhar no repositório |
| [`docs/DEPLOY.md`](docs/DEPLOY.md) | o caminho de `develop` à produção, e o que é automático |
| [`docs/API.md`](docs/API.md) | endpoints e payloads, com coleção do Postman pronta |
| [`reports/relatorio.md`](reports/relatorio.md) | o relatório completo, com todos os resultados |
| [`docs/PLANO.md`](docs/PLANO.md) | fases, riscos e estado de execução |
| [`docs/RUBRICA.md`](docs/RUBRICA.md) | onde cada critério avaliado é atendido |
| [`reports/ciclo_rotulo.html`](reports/ciclo_rotulo.html) | diagramas do ciclo de vida do rótulo |

### Decisões de arquitetura

**Dados e metodologia**

| | |
|---|---|
| [0001](docs/adr/0001-trilha-e-dominio.md) | Trilha A e domínio de detecção de fraude |
| [0002](docs/adr/0002-fonte-de-dados.md) | Ingestão pelo ARFF bruto — `fetch_openml` descarta `Time` |
| [0003](docs/adr/0003-split-temporal.md) | Particionamento cronológico, sem embaralhamento |
| [0005](docs/adr/0005-duplicatas.md) | Duplicatas removidas apenas no treino |
| [0006](docs/adr/0006-desbalanceamento.md) | Ponderação de classe em vez de SMOTE |

**Métrica, modelagem e seleção**

| | |
|---|---|
| [0004](docs/adr/0004-metrica-primaria.md) | PR-AUC no lugar de acurácia e ROC-AUC |
| [0007](docs/adr/0007-baseline-obrigatorio.md) | Baseline interpretável obrigatório |
| [0008](docs/adr/0008-modelo-principal.md) | Gradient boosting com busca bayesiana |
| [0020](docs/adr/0020-criterio-de-adocao.md) | Adoção por teste t pareado |
| [0021](docs/adr/0021-objetivo-do-tuning.md) | Tuning otimiza recall na região de precisão exigida |
| [0022](docs/adr/0022-protocolo-de-medicao.md) | Ranking sobre escore bruto, limiar fora-de-fold |
| [0023](docs/adr/0023-hiperparametros-travados.md) | Hiperparâmetros travados em arquivo versionado |
| [0026](docs/adr/0026-reajuste-em-treino-mais-validacao.md) | Modelo final treinado em treino + validação |

**Calibração e decisão**

| | |
|---|---|
| [0009](docs/adr/0009-calibracao.md) | Calibração explícita das probabilidades |
| [0010](docs/adr/0010-politica-de-decisao.md) | Política de três faixas com restrição de capacidade |
| [0024](docs/adr/0024-piso-de-perda-por-fraude.md) | Piso para a perda por fraude — *card testing* |
| [0025](docs/adr/0025-grade-de-limiares.md) | Grade a partir dos valores distintos do escore |

**Explicabilidade e monitoramento**

| | |
|---|---|
| [0011](docs/adr/0011-explicabilidade.md) | SHAP, e o limite imposto pelo PCA anonimizado |
| [0014](docs/adr/0014-monitoramento.md) | Rótulo atrasado por chargeback e drift por PSI/KS |

**Engenharia e entrega**

| | |
|---|---|
| [0012](docs/adr/0012-fonte-da-verdade.md) | `src/` é a fonte da verdade |
| [0013](docs/adr/0013-reprodutibilidade.md) | Configuração central, sementes e versões travadas |
| [0015](docs/adr/0015-esteira-de-promocao.md) | `develop → homolog → main` com promoção de artefato |
| [0016](docs/adr/0016-versionamento-do-modelo.md) | Versionamento por Conventional Commits |
| [0017](docs/adr/0017-entrega-por-artefato-executavel.md) | Entrega como ecossistema executável |
| [0018](docs/adr/0018-persistencia-operacional.md) | Estado operacional em PostgreSQL, opcional |
| [0019](docs/adr/0019-registry-de-imagens.md) | Imagens no Docker Hub, promovidas por digest |

Índice completo em [`docs/adr/`](docs/adr/README.md). Decisões alteradas **não são
reescritas**: ganham um cabeçalho `Alterada por` e a nova decisão explica o que estava
errado. O histórico de raciocínio é parte do que se entrega.

### Especificações

| | |
|---|---|
| [001](docs/specs/001-ingestao-e-dados.md) | Ingestão, validação da fonte e particionamento |
| [002](docs/specs/002-modelagem.md) | Baseline, tuning e calibração |
| [003](docs/specs/003-avaliacao-e-politica.md) | Métricas, política de três faixas e sensibilidade |
| [004](docs/specs/004-explicabilidade.md) | SHAP global, local e operacional |
| [005](docs/specs/005-monitoramento.md) | PSI, KS, camadas e gatilhos de retreino |
| [006](docs/specs/006-demonstracao-e-entrega.md) | Demonstração, relatório e entrega |
| [007](docs/specs/007-cicd-e-versionamento.md) | Esteira, versionamento e promoção |

---

## Estrutura do repositório

```
config/config.yaml            configuração central — nada fixo em código
  model_params.lock.json      hiperparâmetros travados (ADR-0023)
src/                          o pipeline real (fonte da verdade)
  ingestion.py                  download do ARFF, parsing e validação
  eda.py                        análise exploratória
  preprocessing.py              split cronológico, atributos, escalonamento
  model_selection.py            comparação de candidatos por validação cruzada
  train.py                      baseline + XGBoost com Optuna
  calibration.py                isotônica vs. Platt, Brier e ECE
  policy.py                     política de três faixas e sensibilidade
  evaluate.py                   métricas, ponto de operação, figuras
  explainability.py             SHAP global, local e operacional
  artifacts.py                  persistência do artefato e metadata
  figures.py                    as 15 figuras do relatório
  db.py                         acesso ao banco operacional
monitoring/drift_monitor.py   PSI, KS, camadas e gatilhos
deploy/                       API de inferência e demonstração
frontend/                     console de operação
db/schema.sql                 estado operacional
tests/                        os 20 invariantes
tools/                        montagem do PDF e geração de amostras
docs/adr/                     27 registros de decisão
docs/specs/                   7 especificações
reports/                      relatório, figuras e artefatos JSON
run_pipeline.py               entry point único
```

---

## Princípios que o código respeita

Não são estilo, são correção — cada um tem teste automatizado:

1. **Particionamento cronológico.** Fraude é adversarial e não estacionária; embaralhar
   vaza o futuro e produz métrica que não se realiza em produção.
2. **O teste é tocado uma única vez.** Escalonador, calibrador e limiares saem do treino
   ou das predições fora-de-fold, nunca do teste.
3. **Sem SMOTE.** Interpolar sobre componentes de PCA fabrica transações impossíveis.
4. **Métricas da classe positiva.** Com 0,17% de positivos, média ponderada passa de 0,99
   sem informar nada.
5. **Todo número vem de execução real**, gravado em `reports/*.json` — inclusive os
   desfavoráveis.
6. **Nenhum parâmetro fixo em código.** Tudo em `config/config.yaml`.

---

## Limitações declaradas

- `V1`–`V28` são componentes de PCA anonimizados: **não há** interpretação de negócio
  possível para elas. Apenas `Amount` e `Hour` são semanticamente legíveis.
- As premissas de custo da política são arbitradas — daí a análise de sensibilidade sobre
  125 combinações.
- A faixa de revisão manual opera com volume muito pequeno neste modelo: 99,9% dos
  escores de teste são exatamente zero, efeito dos platôs da calibração isotônica.
- 48 horas de dados não sustentam validação por janela deslizante com positivos
  suficientes.
- `Hour` apresenta PSI de 10,07 entre treino e teste — artefato do desenho experimental,
  e argumento contra mantê-lo em um sistema real.

---

Diego Nunes de Morais
