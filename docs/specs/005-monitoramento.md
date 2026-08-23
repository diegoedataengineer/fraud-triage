# Spec 005 — Monitoramento e detecção de drift

**ADR relacionada:** [0014](../adr/0014-monitoramento.md)

## `monitoring/drift_monitor.py`

**Entrada:** distribuição de referência (treino) e distribuição corrente
**Saída:** `reports/drift_report.json` e figura

### Indicadores

**PSI (Population Stability Index)**, por feature:

```
PSI = Σ (pct_corrente − pct_referencia) · ln(pct_corrente / pct_referencia)
```

Sobre 10 faixas definidas pelos decis **da referência**. Faixas vazias recebem epsilon
para evitar divisão por zero. Interpretação: `< 0,1` estável · `0,1–0,25` atenção ·
`> 0,25` drift relevante.

**Teste KS de duas amostras**, por feature: estatística e p-valor. Com centenas de
milhares de linhas, o p-valor fica significativo para diferenças irrelevantes — por isso
a **magnitude da estatística KS** é o que orienta a decisão, e o p-valor é contexto.

### Camadas implementadas

| Camada | Sinal | Latência |
|---|---|---|
| 1 | PSI e KS das features; distribuição dos escores; frações por faixa | imediata |
| 2 | Precisão na faixa de revisão manual; uso da capacidade | horas |
| 3 | Recall e custo real confirmados por chargeback | semanas |

A camada 3 **nunca** reporta recall sobre janela imatura sem marcá-la como parcial.

### Demonstração

Sem tráfego de produção, o projeto demonstra o mecanismo de duas formas:

1. **Drift real:** treino contra teste — períodos distintos por construção (ADR-0003).
   Qualquer drift aqui é genuíno e digno de discussão.
2. **Drift simulado:** perturbações controladas (deslocamento de média, mudança de escala,
   alteração da distribuição de `Amount`) para mostrar a resposta dos indicadores e
   validar as faixas de alerta.

### Gatilhos de retreino

Declarados em `config.monitoring.triggers`, disparando o que ocorrer primeiro:

- PSI > 0,25 em qualquer feature entre as 10 mais importantes por SHAP;
- queda da precisão na faixa de revisão além da tolerância configurada;
- agenda periódica, como piso de segurança.

### Critérios de aceite

- PSI de uma distribuição contra ela mesma é 0 (tolerância 1e-9) — teste automatizado.
- PSI cresce monotonicamente com a magnitude do deslocamento simulado.
- Drift simulado com deslocamento conhecido é detectado acima do limiar.
- `reports/drift_report.json` traz PSI e KS por feature, ordenados por severidade.


---

## Implementação do disparo

Os gatilhos acima passaram a ser **avaliados por código** em
[`monitoring/check_triggers.py`](../../monitoring/check_triggers.py), e consumidos pelo
workflow [`retrain.yml`](../../.github/workflows/retrain.yml), que roda diariamente e
manda a esteira treinar um candidato quando algum dispara
([ADR-0030](../adr/0030-disparo-do-retreino.md)).

Até a versão `1.5.0` esta especificação descrevia gatilhos que existiam apenas como
configuração: só o PSI era calculado, os outros dois não tinham código, e nada consumia o
resultado.

Três pontos que a implementação deixou explícitos:

1. **`sem dados` não é `estável`.** Um gatilho que não pôde ser avaliado — sem banco, sem
   relatório de drift, sem artefato — declara isso, em vez de responder que está tudo bem.
2. **O disparo treina, não promove.** A promoção continua exigindo revisão humana.
3. **O PSI apurado é treino × teste**, não tráfego de produção contra a referência. É a
   demonstração do mecanismo sobre os dados disponíveis, não um sinal de operação.
