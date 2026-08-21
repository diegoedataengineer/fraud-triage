# Spec 007 — CI/CD, versionamento e promoção do modelo

**ADRs relacionadas:** [0015](../adr/0015-esteira-de-promocao.md) ·
[0016](../adr/0016-versionamento-do-modelo.md) · [0019](../adr/0019-registry-de-imagens.md)

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

**Job `build-and-push`**: constrói e publica as imagens no Docker Hub (ADR-0019).

| Branch | Imagem de treino | Imagem de serving |
|---|---|---|
| `develop` | `dev-<sha7>` | não construída (sem modelo validado) |
| `staging` | `sha-<sha7>` e `staging` | `sha-<sha7>` e `staging` |
| `main` | — | — |

A imagem de serving embute o artefato, então depende do job `train` e só é construída
em `staging`, onde o modelo passou pela porta de qualidade.

### `release.yml` — versionamento

Dispara no push para `main`. Usa `googleapis/release-please-action@v4` com
`release-type: python`. A ação abre um Release PR acumulando as mudanças; ao ser mesclado,
cria a tag `vX.Y.Z`, o CHANGELOG e a Release, e então dispara `deploy-production.yml`
**no ref da tag**.

### `deploy-production.yml` — promoção da imagem

Dispara em tag `v*`. **Não treina e não reconstrói** (ADR-0015 e ADR-0019). Sequência:

1. **Resolver o digest validado:** consultar `fraud-triage:staging` no Docker Hub. Se a
   tag não existir, não há candidato validado e a promoção **falha** — nunca constrói
   para contornar.
2. **Reconferir as métricas** lidas do `metadata.json` de dentro da própria imagem.
   Segunda porta, independente da validação feita em `staging`.
3. **Promover por retag:** `docker buildx imagetools create` aponta `X.Y.Z`, `X.Y`, `X`
   e `latest` ao **mesmo digest**. Reconstruir produziria uma imagem diferente da
   validada, que é exatamente o que a esteira existe para impedir.
4. **Smoke test** da imagem promovida: subir, consultar `/health`, derrubar.
5. **Anexar o `metadata.json`** à Release e registrar o digest promovido nas notas.


## Arquivos de configuração

| Arquivo | Papel |
|---|---|
| `.commitlintrc.json` | tipos, escopos e limites do assunto |
| `Dockerfile` | multi-stage: alvos `trainer` e `serving` |
| `docker-compose.yml` | ecossistema com Postgres (ADR-0018) |
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
- Promoção sem imagem em `staging` falha, em vez de construir.
- O digest de `X.Y.Z` é **idêntico** ao de `sha-<sha7>` validado em `staging`.
- Toda Release `vX.Y.Z` carrega o `metadata.json` com `version` igual a `X.Y.Z`.
- `metadata.json` contém `git_sha`, `data.sha256`, `training.seed`, `metrics` e
  `environment.dependencies` preenchidos.
