# Spec 004 — Explicabilidade

**ADR relacionada:** [0011](../adr/0011-explicabilidade.md)

## `src/explainability.py`

**Entrada:** modelo treinado, amostra do teste, `config.explainability`
**Saída:** figuras em `reports/figures/` e `reports/explainability_summary.json`

### Amostragem

SHAP sobre 284 mil linhas é caro. Usar amostra estratificada do teste com
`config.explainability.sample_size` (padrão 5.000), preservando a proporção de classes e
**garantindo a inclusão de todos os positivos** — são poucos e são o objeto de interesse.
Semente fixa (ADR-0013).

### Três níveis

**1. Global.** `TreeExplainer` + `summary_plot` (beeswarm): quais variáveis mais movem o
modelo e em que direção. Complementar com gráfico de barras da magnitude média absoluta.

**2. Local.** `waterfall` para três casos escolhidos deterministicamente pelo escore:
- um **verdadeiro positivo** de alta confiança;
- um **falso positivo** de alto escore;
- um **falso negativo** de baixo escore.

Os dois últimos são os mais informativos e não podem ser omitidos: mostram onde o modelo
erra e por quê.

**3. Operacional.** Para uma transação na faixa de revisão manual (Spec 003), gerar a
explicação no formato que apoiaria o analista: os principais fatores que empurraram o
escore para cima e para baixo, com a contribuição de cada um.

### Verificação cruzada

Tabela comparando três rankings independentes de importância:

| Fonte | Natureza |
|---|---|
| SHAP (magnitude média absoluta) | local agregado, com direção |
| Importância por ganho do XGBoost | global, sem direção |
| Coeficientes da regressão logística (Spec 002) | global, linear, com direção |

Convergência reforça a leitura; divergência é discutida, não escondida.

### Limitação obrigatória de relatar

`V1`–`V28` são componentes de PCA anonimizados. O relatório deve **declarar
explicitamente** que não é possível atribuir significado de negócio a essas variáveis, e
restringir a interpretação semântica a `Amount` e `Hour`. Atribuir sentido de negócio a
componentes anonimizadas seria fabricação.

### Critérios de aceite

- A amostra contém todos os positivos do teste.
- As figuras são regeneráveis de forma idêntica com a mesma semente.
- `reports/explainability_summary.json` registra o ranking SHAP e a tabela comparativa.
- A seção do relatório contém a declaração de limitação do PCA.
