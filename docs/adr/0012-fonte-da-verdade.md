# ADR-0012 — Manter `src/` como fonte da verdade e o notebook como vitrine

**Status:** Aceita
**Data:** 2026-08-20
**Alterada por:** [ADR-0017](0017-entrega-por-artefato-executavel.md) (papel do notebook)

## Contexto

A entrega exige um notebook do Colab que execute integralmente sem alterações, e ele será
reexecutado na correção. A saída natural seria colocar todo o projeto dentro do notebook.

Notebooks, porém, são ruins como fonte de verdade de um pipeline: misturam código e
estado de execução, permitem execução fora de ordem (uma célula apagada continua valendo
na memória), versionam mal em diff por causa dos metadados JSON, e não são testáveis
isoladamente. A disciplina chama-se **Engenharia** de Aprendizado de Máquina, e 8 dos 40
pontos vão para organização e reprodutibilidade — a estrutura do repositório é parte do
que está sendo avaliado.

Por outro lado, um repositório de scripts sem notebook não atende à entrega e é pior para
narrar resultados, que é o que o notebook faz bem.

## Decisão

Separar os papéis:

- **`src/` é o pipeline real.** Módulos independentes, cada um executável isoladamente
  (`python -m src.ingestion`), orquestrados por um entry point único
  (`run_pipeline.py`). É o que os testes cobrem e o que a CI executa.
- **`notebooks/` é a vitrine.** O notebook clona o repositório, importa `src/` e **narra**
  a execução — EDA, resultados, gráficos, explicabilidade, demonstração. Ele não
  reimplementa a lógica.

Essa dependência é o que garante que notebook e repositório não divirjam: não existem
duas implementações a manter em sincronia, existe uma só, chamada de dois lugares. A
alternativa — copiar o código para dentro do notebook — cria divergência silenciosa no
primeiro ajuste feito de um lado só.

Consequência prática: o repositório precisa estar **público no GitHub** antes da entrega,
já que o notebook o clona.

## Alternativas consideradas

- **Notebook autocontido, com todo o código nas células.** Roda em qualquer lugar, sem
  dependência de repositório público. Descartada por impedir teste automatizado, tornar o
  versionamento inviável e contrariar o que a rubrica de organização avalia.
- **Duplicar a lógica entre `src/` e o notebook.** Removeria o acoplamento. Descartada por
  garantir divergência: os dois deixam de contar a mesma história no primeiro ajuste.
- **Distribuir `src/` como pacote no PyPI e instalar via `pip`.** Mais elegante
  tecnicamente. Descartada por desproporcional ao escopo e por adicionar etapa de
  publicação ao caminho crítico da entrega.

## Consequências

- O notebook fica dependente de o repositório estar público e acessível no momento da
  correção. É risco real; mitigado publicando com antecedência e fixando um **commit ou
  tag específico** no clone, para que a correção execute exatamente a versão entregue.
- Ganhamos testabilidade, diffs legíveis e execução em CI.
- O notebook fica curto e legível: narra e mostra, sem carregar a implementação.
- Uma célula de setup a mais no início do notebook (clone e instalação de dependências).
