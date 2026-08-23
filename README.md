# Triagem de Fraude em Transações de Cartão de Crédito

Projeto de Sistematização da disciplina **Engenharia de Aprendizado de Máquina** —
Trilha A (aprendizado supervisionado).

Pipeline completo de detecção de fraude, da ingestão ao monitoramento, com uma
formulação deliberadamente distinta do classificador binário usual: o modelo alimenta
uma **política de triagem em três faixas** — aprovar, revisar manualmente, bloquear —
sujeita à **capacidade real de revisão manual** e construída sobre probabilidades
**explicitamente calibradas**.

## Para avaliar, um comando

```bash
git clone https://github.com/diegoedataengineer/fraud-triage.git
cd fraud-triage
docker compose up -d
```

Sobe o **ambiente completo** — console, API e banco — a partir de um clone limpo. Não
exige Python instalado, build local, treino prévio, conta em nuvem nem credencial.

| | |
|---|---|
| **Console de operação** | http://localhost:3100 |
| **API, com Swagger** | http://localhost:8000/docs |
| Banco (PostgreSQL) | porta 5432 |

Para encerrar: `docker compose down`. Para apagar também o banco: `docker compose down -v`.

Só a API, sem console nem banco:

```bash
docker run -p 8000:8000 diegodataengineer/fraud-triage:1.6.0
```

> **Versão de entrega: `1.6.0`.** É a versão avaliada, fixada no `docker-compose.yml` e
> referenciada em toda a documentação. Foi promovida pela esteira por *retag* do digest
> validado em homologação — a imagem em produção é, byte a byte, a que passou pela
> verificação, sem reconstrução ([ADR-0019](docs/adr/0019-registry-de-imagens.md)).
>
> **Um número só.** O modelo, a imagem, o `/health`, o metadata do artefato e a tag no
> Docker Hub dizem `1.6.0`. Até a `1.4.1` não era assim: o artefato era carimbado no build
> e a release numerada depois, então a imagem `1.4.1` embarcava o modelo `1.4.0`. Agora a
> versão é anunciada antes de construir ([ADR-0029](docs/adr/0029-versao-unica.md)).
>
> Para fixar outra versão sem editar o compose: `FRAUD_TAG=1.6.0 docker compose up -d`.

---

## Índice

- [Para avaliar, um comando](#para-avaliar-um-comando) — `docker compose up -d`
- [As três formas de rodar](#as-três-formas-de-rodar) — publicado, build local, do código
- [O ecossistema completo](#o-ecossistema-completo) — console, API e banco
- [A esteira treina e publica sozinha](#a-esteira-treina-e-publica-sozinha) — CI/CD verificável
- [Começando do zero](#começando-do-zero) — clonar, instalar, treinar, testar
- [Testes e verificação](#testes-e-verificação)
- [Testar a API](#testar-a-api) — Postman e `curl`
- [Por que três faixas](#por-que-três-faixas-e-não-um-limiar)
- [Resultados](#resultados)
- [Guia da documentação](#guia-da-documentação) — 31 ADRs e 7 especificações
- [Estrutura do repositório](#estrutura-do-repositório)
- [Princípios que o código respeita](#princípios-que-o-código-respeita)
- [Limitações declaradas](#limitações-declaradas)

---

## As três formas de rodar

As três produzem o mesmo sistema. Mudam o quanto se reconstrói pelo caminho.

| | Comando | O que faz | Quanto leva |
|---|---|---|---|
| **1. Imagem publicada** | `docker compose up -d` | usa a imagem promovida em produção, com o modelo já embutido | ~1 min |
| **2. Build local** | `docker compose -f docker-compose.yml -f docker-compose.build.yml up --build` | constrói as imagens a partir deste código | ~5 min |
| **3. Do código, treinando** | `python run_pipeline.py` e depois a opção 2 | treina o modelo do zero e reconstrói tudo | ~15 min |

### 2. Construir localmente

Exige um passo antes, e a ordem importa:

```bash
python run_pipeline.py    # treina e grava o artefato em models/
docker compose -f docker-compose.yml -f docker-compose.build.yml up --build
```

O artefato do modelo **não é versionado no Git** — ele é produto do pipeline, não código
([ADR-0016](docs/adr/0016-versionamento-do-modelo.md)). Construir a imagem de *serving*
antes de treinar produziria uma imagem sem modelo, que sobe e falha ao responder. Por
isso o caminho 1 é o padrão: quem só quer avaliar não precisa treinar nada.

### 3. Reproduzir o treino

O passo a passo completo está em [Começando do zero](#começando-do-zero). Vale saber
desde já que o treino é **determinístico**: duas execuções seguidas produzem métricas
idênticas até a décima casa decimal, matriz de confusão inclusa
([ADR-0023](docs/adr/0023-hiperparametros-travados.md)).

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
models/fraud-triage/<versão>/  modelo, calibrador, política e metadata.json
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
docker compose up -d          # sobe em segundo plano
docker compose logs -f api    # acompanhar a API
docker compose down           # encerrar
```

| Serviço | Papel | Endereço |
|---|---|---|
| `console` | painel de operação e demonstração | http://localhost:3100 |
| `api` | inferência, política e fila de revisão | http://localhost:8000/docs |
| `db` | estado operacional em PostgreSQL | porta 5432 |

Conferir que subiu:

```bash
curl -s localhost:8000/health | python -m json.tool
```

```json
{
  "status": "ok",
  "model_version": "1.6.0",
  "image_version": "1.6.0",
  "git_sha": "…",
  "persistence": true
}
```

`persistence: true` confirma que a API achou o banco. Rodando a imagem avulsa com
`docker run`, sem banco, ela responde `false` e os endpoints de fila devolvem 503 — é o
comportamento esperado, não erro.

### O que fazer no console

Abra `http://localhost:3100` e:

1. **Enviar transação** — uma transação real do teste percorre o diagrama na tela,
   enquanto o inspetor mostra o comando enviado e a resposta de cada etapa, com o tempo.
2. **Fraude conhecida** — envia uma fraude confirmada. *Parte delas será aprovada*: é o
   recall de 0,75 aparecendo ao vivo.
3. **Caso de revisão manual** — pede uma transação que caia na faixa intermediária. Ela
   recebe ~0,1% do volume, porque a política a dimensiona pela capacidade real de
   análise, então sortear ao acaso quase nunca a encontra. Das 49 transações do teste
   nessa faixa, **1 é fraude**: ela concentra incerteza, não fraude — que é a razão de
   ir para uma pessoa em vez de para uma regra.
4. **Clicar numa decisão** — abre o rastro completo daquela transação, com o custo de
   cada etapa em barra proporcional.
5. **Dar veredito na fila** — alimenta a camada 2 do monitoramento, visível em
   `/monitoring/review-precision`.

---

## A esteira treina e publica sozinha

Não há treino manual nem `docker push` na mão. O GitHub Actions **treina o modelo,
verifica a qualidade, publica a imagem, calcula a versão e promove para produção** — e
cada etapa é verificável de fora.

### Os cinco workflows

| Workflow | Dispara em | O que faz |
|---|---|---|
| [`ci.yml`](.github/workflows/ci.yml) | push em `develop`, `homolog`, `main`; disparo | testes, **treina o modelo do zero**, aplica a porta de qualidade e publica o candidato |
| [`retrain.yml`](.github/workflows/retrain.yml) | diário, 06:00 UTC | avalia os gatilhos de monitoramento e **manda retreinar** se algum disparar |
| [`commitlint.yml`](.github/workflows/commitlint.yml) | pull request | recusa mensagem fora de Conventional Commits |
| [`release.yml`](.github/workflows/release.yml) | push em `main` | release-please calcula a versão pelos commits e abre o Release PR |
| [`deploy-production.yml`](.github/workflows/deploy-production.yml) | tag `v*` | reverifica a imagem e **promove por retag**, sem reconstruir |

### O caminho completo de uma mudança

```
commit em develop
      │  ci.yml → testes + treino
      ▼
  homolog
      │  ci.yml → treino + porta de qualidade → publica fraud-triage:homolog e :sha-<sha7>
      ▼
   main
      │  release.yml → Release PR "chore(main): release X.Y.Z"
      ▼  (mesclar o PR)
  tag vX.Y.Z
      │  deploy-production.yml → reverifica → retag → X.Y.Z · X.Y · X · latest
      ▼
  produção
```

**O treino acontece a cada push** nas branches de integração — e é o pipeline inteiro,
da ingestão do dado público ao artefato versionado. Retreinar, aqui, não é um modo
especial: é a mesma esteira executando de novo, e foi o que produziu cada release desta
tabela.

### Quando o monitoramento manda retreinar

Três gatilhos, definidos em `monitoring.triggers` e avaliados por
[`monitoring/check_triggers.py`](monitoring/check_triggers.py):

| Gatilho | Limiar | Camada | Latência do sinal |
|---|---|---|---|
| PSI nos 10 atributos mais influentes | > 0,25 | 1 | imediata, sem rótulo |
| Queda de precisão na fila de revisão | ≥ 10 pontos | 2 | horas |
| Agenda | 30 dias | — | independe de sinal |

```bash
python -m monitoring.check_triggers
```

```
🔴 psi                disparou  · 3 atributo(s) acima de 0.25: Hour, V1, V11
✅ agenda             estável   · treinado há 0 dia(s); limite de 30
⚪ precisao_revisao   sem dados · DATABASE_URL não configurada — sem série para comparar
→ retreino indicado por: psi
```

São **três estados, não dois**. `sem dados` é diferente de `estável`: chamar de estável um
gatilho que não foi verificado afirma algo que ninguém apurou, e é assim que um
monitoramento passa a dar falsa segurança.

O [`retrain.yml`](.github/workflows/retrain.yml) roda essa avaliação diariamente e dispara
a esteira em `homolog` quando algum gatilho acusa. A verificação é diária mesmo com limiar
de 30 dias — só se descobre que a agenda venceu verificando com mais frequência que ela.

### O disparo treina, mas não promove

Um gatilho produz **candidato**. Publicar em produção continua exigindo que uma pessoa
mescle o Release PR.

É deliberado: um gatilho de drift diz que o mundo mudou, não que o modelo novo é melhor.
Promover sozinho trocaria um risco conhecido — o modelo atual envelhecendo — por um
desconhecido, um modelo recém-treinado sobre dados possivelmente contaminados pela própria
mudança que disparou o alarme. Com rótulo chegando em semanas e enviesado por seleção, o
erro levaria semanas para aparecer ([ADR-0030](docs/adr/0030-disparo-do-retreino.md)).

### O limite honesto do sinal de PSI

O PSI é apurado hoje sobre **treino × teste**, não sobre tráfego de produção contra a
referência de treino. Demonstra o mecanismo sobre os dados que existem e confirma que a
base é não estacionária — o que sustenta a escolha do split cronológico —, mas **não é
sinal de produção**. O próprio campo `origem` da saída diz isso. Fechar essa distância
exigiria acumular tráfego real, que este trabalho não tem.

### Como conferir, sem confiar no README

```bash
gh run list --limit 15                    # execuções da esteira
gh release list                           # versões geradas
gh run view <id> --log                    # log de treino de uma execução
```

Ou pelo navegador: [Actions](https://github.com/diegoedataengineer/fraud-triage/actions)
e [Releases](https://github.com/diegoedataengineer/fraud-triage/releases).

**A prova de que promover é retag, e não rebuild:** as tags de produção compartilham o
digest da imagem que a esteira construiu e validou. O comando abaixo verifica sozinho, sem
número escrito à mão:

```bash
IMG=diegodataengineer/fraud-triage
REF=$(docker buildx imagetools inspect $IMG:1.6.0 --format '{{.Manifest.Digest}}')
SHA=$(docker run --rm --entrypoint python $IMG:1.6.0 \
        -c "from src.artifacts import load; print(load()['metadata']['git_sha'][:7])")

for TAG in 1.6.0 1.6 1 latest "sha-$SHA"; do
  D=$(docker buildx imagetools inspect "$IMG:$TAG" --format '{{.Manifest.Digest}}')
  [ "$D" = "$REF" ] && echo "  ok        $TAG" || echo "  DIVERGE   $TAG  $D"
done
```

Todas devem dizer `ok`, inclusive `sha-<commit>` — a tag imutável do candidato construído
naquele commit. A comparação usa `sha-<commit>` de propósito, e **não** `homolog`:
`homolog` é ponteiro móvel, aponta ao último candidato validado e avança a cada push
naquela branch. Comparar com ele daria certo hoje e erraria amanhã, sem que nada tivesse
mudado em produção.

A imagem em produção é, byte a byte, a que foi validada. Reconstruir depois de aprovar
produziria outra imagem — e a aprovação teria sido de algo diferente do que se entrega
([ADR-0019](docs/adr/0019-registry-de-imagens.md)).

O detalhe completo, incluindo o que já esteve quebrado nessa cadeia e como foi corrigido,
está em [docs/DEPLOY.md](docs/DEPLOY.md).

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
