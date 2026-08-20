# ADR-0002 — Ingerir o dataset pelo ARFF bruto do OpenML

**Status:** Aceita
**Data:** 2026-08-20

## Contexto

O enunciado exige base pública, proíbe caminhos locais e determina que "qualquer usuário
consiga executar o notebook do início ao fim sem modificações". A distribuição mais
conhecida do dataset (Kaggle, MLG-ULB) exige credencial: `opendatasets` solicita
usuário e chave de API interativamente, o que quebra a execução automatizada e a
reexecução na correção.

Investigamos as alternativas públicas e medimos o comportamento real de cada uma:

| Fonte | Autenticação | Colunas obtidas | Preserva `Time` |
|---|---|---|---|
| Kaggle via `opendatasets` | **Exige** credencial | 31 | Sim |
| `sklearn.fetch_openml(data_id=1597, return_X_y=True)` | Não | 29 + alvo | **Não** |
| `sklearn.fetch_openml(data_id=1597).frame` | Não | 30 | **Não** |
| **ARFF bruto do OpenML (download direto)** | **Não** | **31** | **Sim** |

O achado decisivo: o OpenML marca `Time` como atributo ignorado em seus metadados, e o
`fetch_openml` do scikit-learn respeita essa marcação **mesmo ao retornar o frame
completo**. A coluna simplesmente não aparece. Como o particionamento cronológico
(ADR-0003) depende inteiramente de `Time`, usar `fetch_openml` inviabilizaria a decisão
metodologicamente mais importante do projeto — e o faria em silêncio, sem erro.

Verificação executada sobre o ARFF bruto, em 2026-08-20:

- 284.807 linhas × 31 colunas (`Time`, `V1`–`V28`, `Amount`, `Class`)
- 492 fraudes → taxa de 0,1727%
- `Time` monotonicamente crescente, cobrindo 48,0 horas
- Zero valores nulos; 1.081 duplicatas exatas
- Download de ~150 MB em ~40 s

## Decisão

Ingerir os dados por **download direto do ARFF publicado pelo OpenML** (data id 1597,
licença pública), com parsing próprio do cabeçalho `@attribute` para recuperar as 31
colunas, e **cache local em Parquet** para que execuções seguintes não repitam o
download.

A etapa de ingestão valida o que baixou antes de liberar o dado adiante: número de
linhas e colunas, presença das colunas esperadas, ausência de nulos e taxa de positivos
dentro de faixa. Se a fonte mudar silenciosamente, o pipeline falha de forma explícita
em vez de treinar sobre dado errado.

## Alternativas consideradas

- **Kaggle via `opendatasets`.** É a distribuição canônica. Descartada por exigir
  credencial: contraria diretamente a exigência de execução sem modificações e tornaria
  a correção dependente de o avaliador possuir conta no Kaggle.
- **`fetch_openml` do scikit-learn.** Seria a opção mais limpa em código. Descartada por
  perder `Time`, o que forçaria particionamento aleatório e vazamento temporal — preço
  alto demais por conveniência de API.
- **Versionar o CSV no próprio repositório.** Garantiria reprodutibilidade absoluta.
  Descartada porque 150 MB em Git é abusivo, e o enunciado pede explicitamente o uso de
  bases públicas em vez de cópias locais.
- **Espelho em bucket próprio.** Removeria a dependência de disponibilidade do OpenML.
  Descartada por acrescentar infraestrutura a manter e por deslocar a fonte de verdade
  para um endereço privado, menos auditável que um repositório público reconhecido.

## Consequências

- A execução passa a depender de rede e da disponibilidade do OpenML. É risco real e
  aceito; o cache em Parquet limita a exposição a uma única execução bem-sucedida.
- Assumimos a manutenção de um parser de ARFF simples, em vez de usar biblioteca pronta.
  O escopo é pequeno e coberto por teste.
- O download inicial de ~150 MB adiciona cerca de 40 segundos à primeira execução do
  notebook. É custo aceitável diante da alternativa de perder o split temporal.
- Se o OpenML remover ou alterar o data id 1597, o pipeline quebra de forma visível. A
  validação da ingestão existe exatamente para que isso não passe despercebido.
