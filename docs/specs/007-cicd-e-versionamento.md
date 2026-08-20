# Spec 007 — CI/CD, versionamento e promoção do modelo

**ADRs relacionadas:** [0015](../adr/0015-esteira-de-promocao.md) ·
[0016](../adr/0016-versionamento-do-modelo.md)

## Convenção de commits

Conventional Commits, validados em toda PR. Formato:
`tipo(escopo): assunto`, assunto com no máximo 72 caracteres e sem inicial maiúscula.

**Escopos válidos**, refletindo as etapas do pipeline:

`data` · `features` · `model` · `calibration` · `policy` · `eval` · `explain` ·
`monitoring` · `serving` · `notebook` · `report` · `deps` · `ci` · `docs`

**Efeito na versão** (ADR-0016):

| Tipo | Versão | Uso típico |
|---|---|---|
| `feat!` ou `BREAKING CHANGE` | MAJOR | features de entrada mudam, schema da API muda |
| `feat` | MINOR | retreino com ganho, novo atributo compatível |
| `fix` | PATCH | recalibração, ajuste de limiar, correção |
| `perf`, `refactor`, `docs` | nenhuma | aparecem no CHANGELOG |
| `chore`, `ci`, `test` | nenhuma | ocultos no CHANGELOG |

## Workflows

### `commitlint.yml` — validação dos commits

Dispara em PR para `main`, `staging` e `develop`. Valida todos os commits do PR contra
`.commitlintrc.json`. Sem commits válidos não há cálculo de versão, então esta é a
primeira porta.

### `ci.yml` — validação e treino

Dispara em push para as três branches e em PR para `main` e `staging`.

**Job `pipeline-guard`** (apenas em PR): recusa PRs fora do fluxo
`develop → staging → main`. PRs para `main` só de `staging` ou `release-please--*`; PRs
para `staging` só de `develop` ou de branches de trabalho (`feat/*`, `fix/*`, `hotfix/*`,
`chore/*`, `docs/*`, `refactor/*`, `perf/*`, `test/*`, `ci/*`).

**Job `test`**: instala as dependências travadas e roda `pytest` — os testes dos
invariantes (particionamento cronológico, nada ajustado no teste, invariância de ranking
da calibração, PSI de distribuição contra si mesma).

**Job `train`**: executa o pipeline. O orçamento de HPO varia por branch, via
`HPO_N_TRIALS`, sem alterar código:

| Branch | Tentativas | Valida mínimos | Publica artefato |
|---|---|---|---|
| `develop` | 5 | não bloqueia | não |
| `staging` | completo (config) | **bloqueia** | sim |
| `main` | — | — | não treina |

Em `staging`, o job **falha** se as mínimas da rubrica não forem atingidas
(`roc_auc ≥ 0,95`, `recall ≥ 0,75`, `precision ≥ 0,80`), lidas de
`reports/evaluation_summary.json`. Falhar aqui é o comportamento correto: impede que um
modelo abaixo do exigido seja promovido.

Artefato publicado: `model-<sha>`, contendo `models/fraud-triage/<versão>/` completo.

### `release.yml` — versionamento

Dispara no push para `main`. Usa `googleapis/release-please-action@v4` com
`release-type: python`. A ação abre um Release PR acumulando as mudanças; ao ser mesclado,
cria a tag `vX.Y.Z`, o CHANGELOG e a Release, e então dispara `deploy-production.yml`
**no ref da tag**.

### `deploy-production.yml` — promoção do artefato

Dispara em tag `v*`. **Não treina** (ADR-0015). Sequência:

1. Localizar a execução bem-sucedida mais recente de `ci.yml` na branch `staging` e
   baixar seu artefato de modelo.
2. **Verificar a procedência:** o `git_sha` do `metadata.json` precisa ser ancestral da
   tag (`git merge-base --is-ancestor`). Se não for, **falhar** — o artefato pertence a
   outra linhagem.
3. **Reconferir as métricas** do `metadata.json` contra os mínimos. Segunda porta,
   independente da primeira.
4. **Carimbar a versão:** gravar a versão da tag no `metadata.json` e renomear o
   diretório do modelo para ela.
5. **Publicar na Release** o artefato e o `metadata.json` — é o registro de modelos
   (ADR-0016).
6. **Deploy simulado:** subir a API, consultar `/health`, executar a demonstração,
   encerrar. É simulação declarada, não deploy real.

Se o artefato de `staging` não for encontrado, o job falha. **Retreinar neste ponto é
proibido** — anularia a garantia de que o modelo servido é o validado.

## Arquivos de configuração

| Arquivo | Papel |
|---|---|
| `.commitlintrc.json` | tipos, escopos e limites do assunto |
| `release-please-config.json` | `release-type: python`, seções do CHANGELOG em português |
| `.release-please-manifest.json` | versão corrente |
| `pyproject.toml` | metadados e versão, atualizada pelo release-please |

## Critérios de aceite

- PR com commit fora do Conventional Commits é recusado.
- PR de `feat/x` direto para `main` é recusado pela guarda de fluxo.
- Push em `staging` com métricas abaixo do mínimo **falha** e não publica artefato.
- `deploy-production` com artefato de linhagem divergente falha na verificação de
  ancestralidade.
- Nenhum caminho da esteira treina modelo em `main` ou em tag.
- Toda Release `vX.Y.Z` carrega artefato e `metadata.json` com `version` igual a `X.Y.Z`.
- `metadata.json` contém `git_sha`, `data.sha256`, `training.seed`, `metrics` e
  `environment.dependencies` preenchidos.
