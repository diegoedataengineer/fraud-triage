-- Estado operacional do sistema de triagem de fraude (ADR-0018).
--
-- As tabelas cobrem as etapas do ciclo de vida que exigem persistencia: o que foi
-- decidido, o que foi para revisao humana, o rotulo que chega semanas depois por
-- chargeback, e a evolucao do drift que dispara retreino.

CREATE TABLE IF NOT EXISTS model_versions (
    version         TEXT PRIMARY KEY,              -- SemVer vindo do release-please (ADR-0016)
    git_sha         TEXT        NOT NULL,
    data_sha256     TEXT        NOT NULL,          -- amarra o modelo aos dados exatos
    metrics         JSONB       NOT NULL,
    thresholds      JSONB       NOT NULL,          -- t_low e t_high da politica de tres faixas
    trained_at      TIMESTAMPTZ NOT NULL,
    promoted_at     TIMESTAMPTZ,
    status          TEXT        NOT NULL DEFAULT 'registered'
                    CHECK (status IN ('registered', 'homolog', 'production', 'archived'))
);

-- Apenas uma versao em producao por vez: a promocao e uma troca, nao um acumulo.
CREATE UNIQUE INDEX IF NOT EXISTS one_production_model
    ON model_versions ((status)) WHERE status = 'production';

CREATE TABLE IF NOT EXISTS transactions (
    id              BIGSERIAL   PRIMARY KEY,
    external_id     TEXT        UNIQUE,
    occurred_at     TIMESTAMPTZ NOT NULL,
    amount          NUMERIC(12, 2) NOT NULL CHECK (amount >= 0),
    features        JSONB       NOT NULL,          -- V1..V28 e derivados, como enviados
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS transactions_occurred_at ON transactions (occurred_at);

CREATE TABLE IF NOT EXISTS decisions (
    id              BIGSERIAL   PRIMARY KEY,
    transaction_id  BIGINT      NOT NULL REFERENCES transactions (id) ON DELETE CASCADE,
    model_version   TEXT        NOT NULL REFERENCES model_versions (version),
    score           DOUBLE PRECISION NOT NULL CHECK (score BETWEEN 0 AND 1),  -- probabilidade calibrada
    band            TEXT        NOT NULL CHECK (band IN ('approve', 'manual_review', 'block')),
    t_low           DOUBLE PRECISION NOT NULL,     -- limiares vigentes no momento da decisao:
    t_high          DOUBLE PRECISION NOT NULL,     -- sem isso a decisao nao e auditavel depois
    explanation     JSONB,                          -- principais fatores SHAP
    decided_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS decisions_band_time ON decisions (band, decided_at);
CREATE INDEX IF NOT EXISTS decisions_model ON decisions (model_version);

-- A faixa do meio da politica: o unico ponto do sistema que gera rotulo em horas
-- em vez de semanas, e por isso a fonte de observabilidade mais rapida (ADR-0014).
CREATE TABLE IF NOT EXISTS review_queue (
    id              BIGSERIAL   PRIMARY KEY,
    decision_id     BIGINT      NOT NULL UNIQUE REFERENCES decisions (id) ON DELETE CASCADE,
    status          TEXT        NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'in_review', 'resolved')),
    assigned_to     TEXT,
    analyst_label   BOOLEAN,                        -- veredito humano: e fraude?
    queued_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at     TIMESTAMPTZ,
    CONSTRAINT resolved_needs_label
        CHECK (status <> 'resolved' OR (analyst_label IS NOT NULL AND resolved_at IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS review_queue_pending ON review_queue (status, queued_at)
    WHERE status <> 'resolved';

-- O rotulo verdadeiro, que so existe quando o titular contesta a cobranca.
-- Transacoes bloqueadas nunca geram chargeback: o vies de selecao e estrutural
-- e precisa ser considerado ao medir desempenho (ADR-0014).
CREATE TABLE IF NOT EXISTS chargebacks (
    transaction_id  BIGINT      PRIMARY KEY REFERENCES transactions (id) ON DELETE CASCADE,
    is_fraud        BOOLEAN     NOT NULL,
    confirmed_at    TIMESTAMPTZ NOT NULL
);

-- A latencia do rotulo e o numero que decide quais janelas ja estao maduras o
-- bastante para reportar recall. Depende de duas tabelas, entao e view e nao
-- coluna gerada.
CREATE OR REPLACE VIEW label_latency AS
SELECT
    c.transaction_id,
    c.is_fraud,
    c.confirmed_at,
    t.occurred_at,
    EXTRACT(DAY FROM c.confirmed_at - t.occurred_at)::INTEGER AS days_to_confirm
FROM chargebacks c
JOIN transactions t ON t.id = c.transaction_id;

CREATE TABLE IF NOT EXISTS drift_metrics (
    id                  BIGSERIAL   PRIMARY KEY,
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    reference_version   TEXT        NOT NULL REFERENCES model_versions (version),
    feature             TEXT        NOT NULL,
    psi                 DOUBLE PRECISION NOT NULL,
    ks_statistic        DOUBLE PRECISION,
    ks_pvalue           DOUBLE PRECISION,
    severity            TEXT        NOT NULL
                        CHECK (severity IN ('stable', 'warning', 'drift'))
);

CREATE INDEX IF NOT EXISTS drift_metrics_series ON drift_metrics (feature, computed_at);

CREATE TABLE IF NOT EXISTS retraining_events (
    id              BIGSERIAL   PRIMARY KEY,
    triggered_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    trigger_reason  TEXT        NOT NULL
                    CHECK (trigger_reason IN ('psi_threshold', 'precision_drop', 'scheduled', 'manual')),
    details         JSONB,
    resulting_version TEXT      REFERENCES model_versions (version)
);

-- Uma linha por decisao, com tudo que se costuma querer consultar junto: a transacao,
-- a decisao com os limiares vigentes, o veredito do analista quando houve, e o rotulo
-- por chargeback quando existir.
--
-- Existe porque a informacao esta corretamente normalizada em quatro tabelas, e
-- reescrever esses JOINs a cada consulta convida a erro — sobretudo o de usar INNER
-- onde precisa ser LEFT, que silenciosamente esconde toda transacao ainda sem veredito
-- ou sem chargeback, que sao a maioria.
--
-- As componentes V1..V28 ficam de fora de proposito: sao 28 colunas anonimizadas que
-- poluem qualquer inspecao manual. Quem precisar delas consulta transactions.features,
-- que e JSONB.
CREATE OR REPLACE VIEW decision_log AS
SELECT
    d.id                AS decision_id,
    t.id                AS transaction_id,
    t.occurred_at,
    t.amount,
    d.model_version,
    d.score,
    d.band,
    d.t_low,
    d.t_high,
    d.decided_at,
    q.status            AS review_status,
    q.analyst_label     AS analyst_says_fraud,
    q.resolved_at       AS analyst_decided_at,
    c.is_fraud          AS chargeback_says_fraud,
    c.confirmed_at      AS chargeback_at,
    -- De onde veio o rotulo, se e que veio. A ordem reflete a confiabilidade: o
    -- chargeback e a verdade, o analista e uma estimativa em horas, e o resto ainda
    -- nao tem rotulo nenhum — que e o estado normal da maioria das transacoes.
    CASE
        WHEN c.transaction_id IS NOT NULL THEN 'chargeback'
        WHEN q.analyst_label  IS NOT NULL THEN 'analista'
        ELSE 'sem rotulo'
    END                 AS label_source
FROM decisions d
JOIN transactions t ON t.id = d.transaction_id
LEFT JOIN review_queue q ON q.decision_id = d.id
LEFT JOIN chargebacks  c ON c.transaction_id = t.id;
