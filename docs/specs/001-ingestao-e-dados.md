# Spec 001 — Ingestão, validação e particionamento

**ADRs relacionadas:** [0002](../adr/0002-fonte-de-dados.md) ·
[0003](../adr/0003-split-temporal.md) · [0005](../adr/0005-duplicatas.md)

## Objetivo

Obter o dataset de forma reprodutível e sem autenticação, provar que o que chegou é o
que se espera, e produzir as partições cronológicas que alimentam todo o resto.

## `src/ingestion.py`

**Entrada:** `config.data.arff_url`, `config.data.raw_cache_path`

**Saída:** `DataFrame` de 284.807 × 31 e cache em Parquet

### Comportamento

1. Se o cache Parquet existir e passar na validação, carregá-lo e encerrar.
2. Caso contrário, baixar o ARFF (~150 MB) com timeout e repetição em caso de falha
   transitória.
3. Parsear o cabeçalho: extrair os nomes de coluna das linhas `@attribute` e ler o corpo
   após `@data` como CSV sem cabeçalho.
4. Converter `Class` para inteiro, removendo aspas do formato ARFF.
5. Validar (abaixo). Falhar de forma explícita se a validação não passar.
6. Gravar o cache em Parquet.

### Validação de ingestão — critérios de aceite

Valores verificados na fonte em 2026-08-20. A validação **falha com erro**, nunca com
aviso: dado errado não pode seguir adiante silenciosamente.

| Verificação | Valor esperado |
|---|---|
| Número de linhas | 284.807 |
| Número de colunas | 31 |
| Colunas presentes | `Time`, `V1`–`V28`, `Amount`, `Class` |
| Valores nulos | 0 |
| Valores distintos de `Class` | `{0, 1}` |
| Contagem de positivos | 492 |
| Taxa de positivos | 0,001727 (tolerância 1e-6) |
| `Time` monotonicamente crescente | verdadeiro |
| Amplitude de `Time` | 172.792 s (48,0 h) |
| `Amount` mínimo | ≥ 0 |

## `src/preprocessing.py`

**Entrada:** `DataFrame` bruto validado
**Saída:** `X_train, y_train, X_val, y_val, X_test, y_test`, o objeto de escalonamento e
um resumo em `reports/preprocessing_summary.json`

### Ordem das operações

A ordem importa e não pode ser alterada — ela é o que impede vazamento:

1. **Ordenar por `Time`** de forma ascendente.
2. **Particionar cronologicamente** em 70/15/15 por posição, sem embaralhar.
3. **Remover duplicatas exatas apenas no treino** (ADR-0005), considerando todas as
   colunas. Registrar quantas foram removidas e quantas eram fraude.
4. **Engenharia de atributos** (abaixo), com toda estatística estimada **apenas no
   treino**.
5. **Escalonar** `Amount` e as features derivadas com `RobustScaler` — ajustado
   exclusivamente no treino, apenas aplicado a validação e teste. `V1`–`V28` já são
   componentes de PCA em escala comparável e não são reescalonadas.

### Engenharia de atributos

Conjunto deliberadamente enxuto: com features anonimizadas, há pouco espaço para
derivação semântica, e cada atributo novo é uma chance a mais de vazamento.

| Atributo | Definição | Justificativa |
|---|---|---|
| `Amount_log` | `log1p(Amount)` | `Amount` é fortemente assimétrico (mediana 22, máximo 25.691) |
| `Hour` | `(Time / 3600) mod 24` | captura sazonalidade intradiária sem carregar tendência absoluta |
| `Amount_zscore_hour` | desvio de `Amount` em relação à média da hora, **estimada no treino** | valor atípico *para aquele horário* é mais informativo que valor absoluto |

`Time` bruto **não** é usado como feature: é índice de particionamento. Mantê-lo levaria
o modelo a aprender o intervalo específico das 48 horas observadas, que não generaliza.

### Critérios de aceite

- Nenhum índice se repete entre treino, validação e teste.
- `max(Time_treino) ≤ min(Time_val)` e `max(Time_val) ≤ min(Time_teste)`.
- O escalonador é ajustado uma única vez, e apenas no treino — coberto por teste.
- Cada partição contém ao menos um positivo (verificação explícita: com 492 positivos e
  corte cronológico, não é garantido a priori).
- `reports/preprocessing_summary.json` registra o tamanho e a taxa de positivos de cada
  partição, as duplicatas removidas e os parâmetros do escalonador.
