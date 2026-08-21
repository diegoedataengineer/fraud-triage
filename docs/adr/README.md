# Registros de Decisão de Arquitetura (ADR)

Cada arquivo aqui registra **uma** decisão técnica relevante do projeto: o contexto que a
provocou, a opção escolhida, as alternativas descartadas e as consequências aceitas.

O objetivo não é documentar o que o código faz — isso é papel do código e das
[especificações](../specs/). O objetivo é preservar **o porquê**, que é a parte que se
perde primeiro e que a banca avaliadora não consegue inferir lendo o notebook.

Uma ADR aceita não é reescrita quando muda de ideia: cria-se uma nova ADR que a
substitui, e a antiga passa a `Substituída por ADR-XXXX`. O histórico de raciocínio é
tão importante quanto a conclusão.

## Índice

| ADR | Decisão | Status |
|---|---|---|
| [0001](0001-trilha-e-dominio.md) | Trilha A (supervisionado) e domínio de detecção de fraude | Aceita |
| [0002](0002-fonte-de-dados.md) | Ingestão pelo ARFF bruto do OpenML, não por `fetch_openml` nem Kaggle | Aceita |
| [0003](0003-split-temporal.md) | Particionamento cronológico, sem embaralhamento | Aceita |
| [0004](0004-metrica-primaria.md) | PR-AUC como métrica primária de seleção | Aceita |
| [0005](0005-duplicatas.md) | Remoção de duplicatas exatas apenas no treino | Aceita |
| [0006](0006-desbalanceamento.md) | Ponderação de classe em vez de SMOTE ou undersampling | Aceita |
| [0007](0007-baseline-obrigatorio.md) | Baseline interpretável obrigatório antes do modelo principal | Aceita |
| [0008](0008-modelo-principal.md) | Gradient boosting com busca de hiperparâmetros via Optuna | Aceita |
| [0009](0009-calibracao.md) | Calibração explícita das probabilidades | Aceita |
| [0010](0010-politica-de-decisao.md) | Política de triagem em três faixas com restrição de capacidade | Aceita |
| [0011](0011-explicabilidade.md) | SHAP como técnica principal de explicabilidade | Aceita |
| [0012](0012-fonte-da-verdade.md) | `src/` é a fonte da verdade; o notebook é vitrine | Aceita |
| [0013](0013-reprodutibilidade.md) | Configuração central, sementes fixas e versões travadas | Aceita |
| [0014](0014-monitoramento.md) | Monitoramento com rótulo atrasado e drift por PSI/KS | Aceita |
| [0015](0015-esteira-de-promocao.md) | Fluxo `develop → staging → main` com promoção de artefato | Aceita |
| [0016](0016-versionamento-do-modelo.md) | Versionamento do modelo por Conventional Commits e release-please | Aceita |
| [0017](0017-entrega-por-artefato-executavel.md) | Entrega de ecossistema executável em vez de notebook | Aceita |
| [0018](0018-persistencia-operacional.md) | Estado operacional em PostgreSQL, opcional por configuração | Aceita |
| [0019](0019-registry-de-imagens.md) | Imagens no Docker Hub, promovidas por digest | Aceita |

## Modelo

Novas decisões seguem o [modelo em branco](0000-template.md).
