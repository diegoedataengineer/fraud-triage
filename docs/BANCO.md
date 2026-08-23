# Consultando o banco

O PostgreSQL guarda o **estado operacional**: cada transação recebida, a decisão tomada
com os limiares vigentes naquele momento, a fila de revisão manual e o veredito do
analista.

Não é o dado de treino. O treino lê a base pública ([ADR-0002](adr/0002-fonte-de-dados.md));
este banco registra o que o sistema **decidiu em execução**.

---

## Conectar

Com o ecossistema no ar (`docker compose up -d`):

```bash
docker compose exec db psql -U fraud -d fraud_triage
```

Ou de qualquer cliente, pela porta publicada:

```
host      localhost      porta   5432
banco     fraud_triage   usuário fraud    senha fraud
```

> Credenciais fixas e triviais de propósito: é um ambiente de demonstração, sem dado real.
> Num sistema de verdade viriam de segredo injetado, nunca do `docker-compose.yml`.

---

## A consulta que responde quase tudo

A view **`decision_log`** reúne uma linha por decisão, com transação, política aplicada,
veredito do analista e rótulo por chargeback:

```sql
SELECT decision_id, amount, round(score::numeric, 6) AS score, band,
       review_status, analyst_says_fraud, label_source
FROM decision_log
ORDER BY decision_id DESC
LIMIT 20;
```

```
 decision_id | amount |  score   |     band      | review_status | analyst_says_fraud | label_source
-------------+--------+----------+---------------+---------------+--------------------+--------------
         908 | 302.67 | 0.039604 | manual_review | pending       |                    | sem rotulo
         907 |   0.77 | 0.000000 | approve       |               |                    | sem rotulo
```

Ela existe porque a informação está corretamente normalizada em quatro tabelas, e
reescrever esses `JOIN`s a cada consulta convida ao erro — sobretudo usar `INNER` onde
precisa ser `LEFT`, que silenciosamente esconde toda transação ainda sem veredito ou sem
chargeback. Que são a maioria.

As componentes `V1`–`V28` ficam **fora** da view: 28 colunas anonimizadas poluem qualquer
inspeção manual. Quem precisar delas consulta `transactions.features`, que é `JSONB`.

---

## Consultas úteis

**Quantas transações e como foram decididas**

```sql
SELECT band, count(*), round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct
FROM decisions
GROUP BY band
ORDER BY count(*) DESC;
```

**A fila de revisão, o que está pendente**

```sql
SELECT q.id, t.amount, round(d.score::numeric, 6) AS score, q.queued_at
FROM review_queue q
JOIN decisions d ON d.id = q.decision_id
JOIN transactions t ON t.id = d.transaction_id
WHERE q.status <> 'resolved'
ORDER BY d.score DESC;
```

**O que o analista já decidiu, e se bateu com o chargeback**

```sql
SELECT decision_id, amount, analyst_says_fraud, chargeback_says_fraud,
       analyst_says_fraud = chargeback_says_fraud AS analista_acertou
FROM decision_log
WHERE analyst_says_fraud IS NOT NULL
ORDER BY analyst_decided_at DESC;
```

**Uma transação inteira, com as componentes**

```sql
SELECT t.id, t.amount, t.occurred_at, jsonb_pretty(t.features)
FROM transactions t
WHERE t.id = 1;
```

**A política mudou entre duas decisões?**

Os limiares são gravados junto com a decisão. Sem isso, uma decisão passada deixaria de
ser auditável assim que a política mudasse:

```sql
SELECT model_version, t_low, t_high, count(*), min(decided_at), max(decided_at)
FROM decisions
GROUP BY model_version, t_low, t_high
ORDER BY min(decided_at);
```

**Qual modelo está em produção**

Apenas uma versão pode estar em produção por vez — o schema tem um índice único que
garante isso, porque a promoção é uma **troca**, não um acúmulo:

```sql
SELECT version, git_sha, trained_at, promoted_at,
       metrics->>'roc_auc'   AS roc_auc,
       metrics->>'precision' AS precision
FROM model_versions
WHERE status = 'production';
```

**O histórico de versões que já decidiram algo**

```sql
SELECT version, status, trained_at, thresholds
FROM model_versions
ORDER BY trained_at DESC;
```

---

## As tabelas

| Tabela | O que guarda |
|---|---|
| `transactions` | transação recebida, com `V1`–`V28`, `Time` e `Amount` em JSONB |
| `decisions` | escore, faixa, **limiares vigentes**, versão do modelo e fatores SHAP |
| `review_queue` | fila da faixa intermediária e o veredito do analista |
| `chargebacks` | rótulo verdadeiro, quando o titular contesta a cobrança |
| `model_versions` | versões registradas, com métricas; uma única em produção |
| `drift_metrics` | série de PSI e KS por atributo |
| `retraining_events` | disparos de retreino e o motivo |

| View | O que resolve |
|---|---|
| `decision_log` | uma linha por decisão, com tudo que se costuma querer junto |
| `label_latency` | quantos dias o chargeback levou para confirmar cada transação |

---

## Duas tabelas que estarão vazias, e por quê

**`chargebacks`.** O rótulo verdadeiro vem do titular contestando a cobrança, semanas
depois — e **só para transações que não foram bloqueadas**, porque o cliente nunca chega a
ser cobrado pelas que foram. O viés de seleção é estrutural: quanto melhor o modelo
bloqueia, menos evidência resta de que estava certo ([ADR-0014](adr/0014-monitoramento.md)).
Este trabalho não tem como preenchê-la.

**`retraining_events`.** Registraria os disparos de retreino. O agendador existe e avalia
os gatilhos ([ADR-0030](adr/0030-disparo-do-retreino.md)), mas roda no GitHub Actions, sem
acesso a este banco — que é local ao ambiente de demonstração.

Ambas fazem parte do desenho e estão declaradas em vez de omitidas: um schema que só
contém o que já foi preenchido esconde o que o sistema precisaria para operar de verdade.

---

## Zerar o banco

```bash
docker compose down -v && docker compose up -d
```

O `-v` apaga o volume. O schema em `db/schema.sql` é aplicado **apenas na primeira
inicialização do volume** — então alterações nele só valem depois de um `down -v`, ou
aplicando à mão:

```bash
docker compose exec -T db psql -U fraud -d fraud_triage < db/schema.sql
```
