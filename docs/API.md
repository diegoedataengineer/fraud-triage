# API de inferência — endpoints e payloads

Referência para exercitar o serviço em Postman, `curl` ou qualquer cliente HTTP.

Uma coleção pronta do Postman está em
[`postman/fraud-triage.postman_collection.json`](../postman/fraud-triage.postman_collection.json)
— importe pelo botão **Import** e as 11 requisições já vêm com payloads reais.

---

## Subir o serviço

Só a API, sem banco:

```bash
docker run -p 8000:8000 diegodataengineer/fraud-triage:1.4.0
```

Ecossistema completo, com PostgreSQL e o console de operação:

```bash
docker compose up
```

| | |
|---|---|
| API | http://localhost:8000 |
| Swagger interativo | http://localhost:8000/docs |
| Console | http://localhost:3100 |

Sem `DATABASE_URL` a API responde inferência normalmente e **não persiste**. Os endpoints
de fila de revisão respondem **503** nesse caso — comportamento esperado, não erro.

---

## Endpoints

| Método | Rota | Precisa de banco |
|---|---|---|
| `GET` | `/health` | não |
| `GET` | `/stats` | não |
| `POST` | `/predict` | não |
| `GET` | `/simulate/sample` | não |
| `GET` | `/review/queue` | **sim** |
| `POST` | `/review/{id}/resolve` | **sim** |
| `GET` | `/monitoring/review-precision` | **sim** |

---

## `GET /health`

Confirma que o serviço subiu e devolve a versão do modelo, o commit que o gerou e as
métricas gravadas no artefato. É o primeiro a chamar.

```bash
curl -s http://localhost:8000/health
```

```json
{
  "status": "ok",
  "model_version": "1.1.0",
  "git_sha": "…",
  "metrics": { "roc_auc": 0.9856, "precision": 0.78, "recall": 0.75, "…": "…" },
  "persistence": true
}
```

---

## `POST /predict`

O endpoint principal. Recebe uma transação e devolve a decisão.

**Corpo** — três campos, todos obrigatórios:

| Campo | Tipo | Descrição |
|---|---|---|
| `Time` | número | segundos desde a primeira transação da base |
| `Amount` | número | valor da transação |
| `V` | lista de 28 números | componentes de PCA `V1` a `V28`, nessa ordem |

**Parâmetro opcional:** `?trace=true` acrescenta o rastro por etapa.

### O jeito mais rápido de testar

Pegue uma transação real da própria API e envie:

```bash
curl -s "http://localhost:8000/simulate/sample?kind=fraud" \
  | jq -c .transaction \
  | curl -s -X POST http://localhost:8000/predict \
      -H 'Content-Type: application/json' -d @-
```

### Payload completo, para colar no Postman

Transação **real** do conjunto de teste, rotulada como fraude:

```json
{
  "Time": 155965.0,
  "Amount": 0.77,
  "V": [
    -1.201398,
    4.864535,
    -8.328823,
    7.652399,
    -0.167445,
    -2.767695,
    -3.176421,
    1.623279,
    -4.367228,
    -5.533443,
    4.106405,
    -6.331825,
    0.671785,
    -12.156587,
    1.020252,
    -2.110863,
    -1.558545,
    0.195992,
    0.502453,
    0.597026,
    0.53232,
    -0.556913,
    0.192444,
    -0.698588,
    0.025003,
    0.514968,
    0.378105,
    -0.053133
  ]
}
```

**Resposta esperada:**

```json
{
  "probability": 1.0,
  "band": "block",
  "action": "bloquear automaticamente",
  "thresholds": {
    "t_low": 0.02857142857142857,
    "t_high": 0.5714285714285714
  },
  "model_version": "1.1.0",
  "decision_id": 238
}
```

### Faixas possíveis

| `band` | Significado |
|---|---|
| `approve` | aprovar automaticamente — `p < t_low` |
| `manual_review` | encaminhar ao analista — `t_low ≤ p < t_high` |
| `block` | bloquear automaticamente — `p ≥ t_high` |

---

## `POST /predict?trace=true`

Mesma inferência, devolvendo os valores intermediários de cada etapa com o tempo gasto.
É o que torna o caminho auditável em vez de caixa-preta.

```bash
curl -s -X POST "http://localhost:8000/predict?trace=true" \
  -H 'Content-Type: application/json' -d @transacao.json | jq .trace
```

```json
[
  { "step": "entrada",           "ms": 0.331, "detail": { "atributos_recebidos": 30, "…": "…" } },
  { "step": "pre_processamento", "ms": 2.629, "detail": { "atributos_gerados": 32, "…": "…" } },
  { "step": "modelo",            "ms": 4.388, "detail": { "escore_bruto": 0.0113 } },
  { "step": "calibracao",        "ms": 0.101, "detail": { "metodo": "isotonic", "…": "…" } },
  { "step": "politica",          "ms": 0.005, "detail": { "comparacao": "…", "faixa": "…" } },
  { "step": "persistencia",      "ms": 1.668, "detail": { "decision_id": 34 } },
  { "step": "total",             "ms": 9.122, "detail": { "etapas": 6 } }
]
```

Repare que **calibração e política somam cerca de 0,1 ms**: a política de três faixas não
impõe custo de latência, é aritmética sobre um número já calculado.

---

## `GET /simulate/sample`

Devolve uma transação real do conjunto de teste, com o rótulo verdadeiro — permite
conferir se a decisão do modelo está certa.

| `kind` | Efeito |
|---|---|
| `random` | qualquer uma das 192 embutidas |
| `fraud` | sorteia entre as 52 fraudes |
| `legitimate` | sorteia entre as legítimas |

```bash
curl -s "http://localhost:8000/simulate/sample?kind=fraud" | jq '{Amount: .transaction.Amount, is_fraud}'
```

> **Ao testar com `kind=fraud`, parte das transações será aprovada.** É o recall de 0,75
> aparecendo: o modelo deixa passar uma em cada quatro fraudes. Está documentado no
> relatório, não é defeito da API.

---

## `GET /stats`

Versão em uso, limiares da política, contagem por faixa e latência em janela deslizante
de 500 requisições. Os contadores zeram a cada reinício do serviço.

```bash
curl -s http://localhost:8000/stats | jq '{processed, bands, latency}'
```

---

## Fila de revisão manual

Estes três exigem banco. Suba com `docker compose up`.

### `GET /review/queue`

Casos na faixa intermediária aguardando veredito humano.

```bash
curl -s "http://localhost:8000/review/queue?limit=50" | jq
```

A faixa captura cerca de 0,03% do volume, então a fila costuma vir vazia. Envie várias
transações antes de consultar, ou use o botão **Caso de fronteira** no console, que busca
dirigidamente uma transação que caia entre os limiares.

### `POST /review/{id}/resolve`

Registra a decisão do analista e alimenta a camada 2 do monitoramento.

```bash
curl -s -X POST http://localhost:8000/review/1/resolve \
  -H 'Content-Type: application/json' \
  -d '{"is_fraud": true, "analyst": "professor"}'
```

O `id` vem de `/review/queue`. Um caso já resolvido responde **404**.

### `GET /monitoring/review-precision`

Precisão sobre os casos já revisados, em janela configurável. É o sinal de qualidade mais
rápido do sistema — o rótulo verdadeiro por chargeback levaria semanas.

```bash
curl -s "http://localhost:8000/monitoring/review-precision?window_hours=24" | jq
```

---

## Códigos de resposta

| Código | Quando |
|---|---|
| `200` | sucesso |
| `404` | caso de revisão inexistente ou já resolvido |
| `422` | corpo inválido — falta campo, ou `V` sem exatamente 28 valores |
| `503` | modelo ainda carregando, ou endpoint de fila sem `DATABASE_URL` |

---

## Um roteiro de teste em cinco passos

```bash
# 1. o serviço está no ar?
curl -s localhost:8000/health | jq '{model_version, persistence}'

# 2. pegar uma fraude real e decidir sobre ela
curl -s "localhost:8000/simulate/sample?kind=fraud" | jq -c .transaction \
  | curl -s -X POST localhost:8000/predict -H 'Content-Type: application/json' -d @- | jq

# 3. ver o caminho completo, etapa por etapa
curl -s "localhost:8000/simulate/sample?kind=fraud" | jq -c .transaction \
  | curl -s -X POST "localhost:8000/predict?trace=true" -H 'Content-Type: application/json' -d @- \
  | jq '.trace[] | {step, ms}'

# 4. gerar volume e olhar a operação
for i in $(seq 1 30); do
  curl -s "localhost:8000/simulate/sample?kind=random" | jq -c .transaction \
    | curl -s -X POST localhost:8000/predict -H 'Content-Type: application/json' -d @- > /dev/null
done
curl -s localhost:8000/stats | jq '{processed, bands, latency: .latency.mean_ms}'

# 5. a fila recebeu alguém?
curl -s localhost:8000/review/queue | jq '{pending}'
```
