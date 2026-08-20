# Especificações Técnicas

As [ADRs](../adr/) registram **por que** cada decisão foi tomada. Estes documentos
registram **o que** deve ser construído e **como se verifica** que está correto.

Cada especificação define entradas, saídas, contratos entre módulos e critérios de
aceite verificáveis. Um critério de aceite que não pode ser checado por um teste ou por
uma inspeção objetiva não é critério de aceite.

| Spec | Escopo | Módulo |
|---|---|---|
| [001](001-ingestao-e-dados.md) | Ingestão, validação e particionamento | `src/ingestion.py`, `src/preprocessing.py` |
| [002](002-modelagem.md) | Baseline, modelo principal, tuning e calibração | `src/train.py`, `src/calibration.py` |
| [003](003-avaliacao-e-politica.md) | Métricas, política de três faixas, sensibilidade | `src/evaluate.py`, `src/policy.py` |
| [004](004-explicabilidade.md) | SHAP global, local e operacional | `src/explainability.py` |
| [005](005-monitoramento.md) | PSI, KS, camadas de monitoramento, gatilhos | `monitoring/drift_monitor.py` |
| [006](006-demonstracao-e-entrega.md) | Demonstração com Faker, notebook, relatório, PDF | `deploy/`, `notebooks/`, `reports/` |

## Convenções válidas para todas as specs

- Nenhum caminho absoluto. Tudo deriva da raiz do repositório.
- Nenhum parâmetro fixo em código: valores vêm de `config/config.yaml` (ADR-0013).
- Toda função que sorteia recebe a semente explicitamente.
- Todo artefato numérico é gravado em JSON em `reports/`, para comparação objetiva
  entre execuções.
- Cada módulo é executável isoladamente via `python -m src.<modulo>` (ADR-0012).
