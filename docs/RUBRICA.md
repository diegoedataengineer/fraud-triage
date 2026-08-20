# Mapeamento da rubrica

40 pontos, sete critérios. A tabela liga cada critério ao artefato que o atende e ao
documento que o especifica — para que nenhum ponto dependa de improviso no fim do prazo.

| # | Critério | Pts | Onde é atendido | Spec / ADR |
|---|---|---|---|---|
| 1 | Notebook executado, organização, clareza e reprodutibilidade | **8** | `src/` modular + `config.yaml` central + notebook que importa de `src/` + versões travadas + sementes fixas + esteira com versionamento semântico automático e promoção de artefato | [Spec 006](specs/006-demonstracao-e-entrega.md) · [Spec 007](specs/007-cicd-e-versionamento.md) · [ADR-0012](adr/0012-fonte-da-verdade.md) · [ADR-0013](adr/0013-reprodutibilidade.md) · [ADR-0015](adr/0015-esteira-de-promocao.md) · [ADR-0016](adr/0016-versionamento-do-modelo.md) |
| 2 | Pré-processamento e engenharia de atributos | **5** | Split cronológico, dedup só no treino, `RobustScaler` ajustado só no treino, 3 atributos derivados justificados | [Spec 001](specs/001-ingestao-e-dados.md) · [ADR-0003](adr/0003-split-temporal.md) · [ADR-0005](adr/0005-duplicatas.md) |
| 3 | Modelagem e validação | **7** | Baseline obrigatório + XGBoost com Optuna + `TimeSeriesSplit` + gap de generalização reportado + calibração | [Spec 002](specs/002-modelagem.md) · [ADR-0007](adr/0007-baseline-obrigatorio.md) · [ADR-0008](adr/0008-modelo-principal.md) · [ADR-0009](adr/0009-calibracao.md) |
| 4 | Atendimento às métricas mínimas | **7** | AUC-ROC ≥ 0,95 · Recall ≥ 0,75 · Precision ≥ 0,80, verificados no teste e gravados em JSON | [Spec 003](specs/003-avaliacao-e-politica.md) · [ADR-0004](adr/0004-metrica-primaria.md) |
| 5 | Explicabilidade | **5** | SHAP global, local (VP/FP/FN) e operacional + verificação cruzada com 3 fontes + limitação do PCA declarada | [Spec 004](specs/004-explicabilidade.md) · [ADR-0011](adr/0011-explicabilidade.md) |
| 6 | Estratégia de monitoramento | **3** | Três camadas com rótulo atrasado por chargeback + PSI/KS + gatilhos de retreino + drift simulado + esteira de retreino e promoção | [Spec 005](specs/005-monitoramento.md) · [Spec 007](specs/007-cicd-e-versionamento.md) · [ADR-0014](adr/0014-monitoramento.md) |
| 7 | Organização do relatório e apresentação | **5** | Relatório na estrutura exigida, com números vindos de `reports/*.json` + seção de achados honestos + vídeo | [Spec 006](specs/006-demonstracao-e-entrega.md) |

## Onde a nota costuma escapar

**Critério 4 é binário e vale 7 pontos.** Ou as métricas são atingidas, ou não. Foi o
fator decisivo na escolha da trilha ([ADR-0001](adr/0001-trilha-e-dominio.md)): os
mínimos da A2 são folgados para um gradient boosting bem ajustado, ao contrário dos de
A1 e A3.

**Critério 1 é o de maior peso e não depende do modelo.** Organização e
reprodutibilidade são conquistadas por estrutura, não por acurácia — é a parte mais
controlável dos 40 pontos.

**A reexecução na correção pode descontar nota retroativamente.** "Diferenças
significativas nas métricas poderão resultar em desconto." Por isso as sementes fixas e
versões travadas não são zelo excessivo: são proteção direta de nota.

**Análise crítica pontua mais que número bonito.** Os critérios 3, 5 e 7 recompensam
discussão honesta. Reportar o gap de generalização, a limitação do PCA e as premissas
arbitradas de custo vale mais que escondê-los — e esconder, se percebido, custa
credibilidade em toda a avaliação.
