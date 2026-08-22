# Processo de deploy até produção

Como uma mudança sai da máquina de desenvolvimento e chega a uma imagem servindo
inferência em produção — o que é automático, o que exige ação humana, e o que fazer
quando falha.

Decisões de fundo em [ADR-0015](adr/0015-esteira-de-promocao.md) (promoção de artefato),
[ADR-0016](adr/0016-versionamento-do-modelo.md) (versionamento) e
[ADR-0019](adr/0019-registry-de-imagens.md) (registro de imagens).

---

## O fluxo completo

```
 feat/* fix/* …
      │  PR
      ▼
  ┌─────────┐   push    ┌──────────────────────────────┐
  │ develop │──────────▶│ CI: testes + treino (HPO=5)  │
  └─────────┘           │ publica  dev-<sha7>          │
      │  PR             └──────────────────────────────┘
      ▼
  ┌─────────┐   push    ┌──────────────────────────────┐
  │ homolog │──────────▶│ CI: testes + treino completo │
  └─────────┘           │ PORTA DE QUALIDADE           │
      │  PR             │ publica  homolog + sha-<sha7>│
      ▼                 └──────────────────────────────┘
  ┌─────────┐   push    ┌──────────────────────────────┐
  │  main   │──────────▶│ release-please abre Release PR│
  └─────────┘           └──────────────────────────────┘
      │  merge do Release PR
      ▼
  ┌─────────┐   push    ┌──────────────────────────────┐
  │ tag vX  │──────────▶│ Deploy — Production          │
  └─────────┘           │ RETAG do digest de homolog   │
                        │ X.Y.Z · X.Y · X · latest     │
                        └──────────────────────────────┘
```

**O princípio que governa tudo: treina uma vez, promove o artefato.** Produção não
executa `run_pipeline.py`. Ela reaponta as tags semânticas ao **digest exato** que já
passou pela porta de qualidade em homologação. Reconstruir a partir do mesmo commit
produziria um binário diferente — camadas com outros carimbos de tempo, dependências
transitivas resolvidas em outro instante — e o que iria a produção deixaria de ser o que
foi validado.

---

## O que cada estágio faz

### `develop` — iteração rápida

| | |
|---|---|
| Dispara | push na branch |
| Testes | sim |
| Treino | sim, com `HPO_N_TRIALS=5` |
| Porta de qualidade | não bloqueia |
| Publica | `fraud-triage-trainer:dev-<sha7>` |

O orçamento reduzido existe para dar retorno em minutos. O modelo produzido aqui é
descartável.

### `homolog` — o portão real

| | |
|---|---|
| Dispara | push na branch |
| Treino | completo, orçamento de `config/config.yaml` |
| Porta de qualidade | **bloqueia** — `python -m src.verify_minimums`, contra `evaluation.ci_gate` |
| Publica | `fraud-triage:homolog` e `:sha-<sha7>` (serving e trainer) |

A porta lê `reports/evaluation_summary.json` e reprova a build se os limiares de
`evaluation.ci_gate` não forem atingidos — que são **distintos** dos mínimos da rubrica
([ADR-0027](adr/0027-porta-da-esteira.md)). Onde houver diferença, ela é uma exceção
declarada em configuração, e a saída da verificação a anuncia:

```
✅ precision  0.7800 ≥ 0.75  (exceção — rubrica exige 0.80)
``` **Build reprovada não publica imagem**, e sem imagem em `homolog`
não há candidato para promover — a produção falha de forma explícita em vez de promover
algo não validado.

### `main` — cálculo da versão

Push em `main` aciona o `release-please`, que lê os Conventional Commits, calcula a
próxima versão semântica e abre um **Release PR**. Nada é publicado ainda: o PR acumula
as mudanças e aguarda revisão.

Ao ser mesclado, ele cria a tag `vX.Y.Z`, o CHANGELOG e a Release do GitHub.

### `tag v*` — promoção

Dispara em qualquer tag `v*`. **Não treina e não reconstrói.**

1. Localiza o digest de `fraud-triage:homolog` no Docker Hub. **Se não existir, aborta.**
2. Lê o `metadata.json` de dentro da própria imagem e reconfere os mínimos da rubrica —
   segunda porta, independente da primeira.
3. Reaponta `X.Y.Z`, `X.Y`, `X` e `latest` ao mesmo digest, via
   `docker buildx imagetools create`.
4. Sobe a imagem promovida, consulta `/health` e derruba.
5. Anexa o `metadata.json` à Release.

---

## O que exige ação humana

A esteira é automática do push à publicação da imagem, com **três pontos deliberadamente
manuais**:

**Abrir o PR entre estágios.** `develop → homolog → main` passa por Pull Request. A
guarda de fluxo (`pipeline-guard`) recusa PRs fora dessa ordem — para `main` só a partir
de `homolog` ou de branch do release-please.

**Mesclar o Release PR.** É o momento em que alguém decide que aquela versão vai a
produção. Automatizá-lo tiraria a única aprovação consciente do processo.

**Aprovar o ambiente `production`**, se configurado com gate no GitHub.

---

## Fazer uma release

```bash
# 1. trabalhar em branch de feature, com Conventional Commits
git checkout -b feat/nova-coisa
git commit -m "feat(model): retreina com atributo de velocidade"

# 2. PR para develop, depois para homolog
#    a CI de homolog treina e publica  fraud-triage:homolog

# 3. PR de homolog para main
#    o release-please abre o Release PR

# 4. mesclar o Release PR  →  cria a tag  →  dispara a promoção
```

O tipo do commit define o incremento: `feat` sobe MINOR, `fix` sobe PATCH, `feat!` ou
`BREAKING CHANGE` sobem MAJOR. Para forçar uma versão específica, use o rodapé
`Release-As: 1.2.3`.

---

## Verificação

```bash
# a esteira publicou o candidato?
docker manifest inspect diegodataengineer/fraud-triage:homolog

# o que está em produção
docker run --rm diegodataengineer/fraud-triage:1.1.0 \
  python -c "import json;print(json.load(open('/app/models/fraud-triage/1.1.0/metadata.json'))['git_sha'])"

# execuções da esteira
gh run list --limit 10
```

---

## Falhas conhecidas e o que significam

### `Nenhuma imagem validada em homolog. Promoção abortada.`

Não há candidato publicado. Três causas possíveis, em ordem de frequência:

**A CI de homolog ainda está rodando.** O treino leva cerca de 16 minutos. Criar a tag
logo após empurrar `homolog` gera uma corrida: a promoção dispara antes de a imagem
existir. Aguarde a CI concluir e reexecute o workflow de produção.

**A porta de qualidade reprovou.** As métricas ficaram abaixo do mínimo e a imagem não
foi publicada — o comportamento correto. Verifique
`reports/evaluation_summary.json` na execução.

**A CI pulou os jobs de treino e build.** Foi um defeito real deste repositório: o
GitHub Actions propaga `skipped` **transitivamente**, e como o `pipeline-guard` só roda
em pull request, todo job a jusante era pulado em push. A CI reportava verde tendo
executado apenas os testes. Corrigido com `always()` e verificação explícita do
resultado da dependência. Se ressurgir, confira em `gh run view <id> --json jobs` se
`Train and validate model` aparece como `skipped`.

### `duplicate key value violates unique constraint "one_production_model"`

O registro de modelos aceita uma única versão em produção. Promover uma nova exige
rebaixar a anterior na mesma transação — o código faz isso, mas a falha surgiria se
alguém inserisse manualmente na tabela.

### O console responde 403 com os arquivos no lugar

Bind mount fixa o inode do diretório no momento em que o contêiner sobe. Substituir o
diretório no host deixa o mount apontando para um inode órfão, e o nginx enxerga um
diretório vazio. `docker compose up -d --force-recreate console` reata.

---

## Estado atual da automação

Registrado por honestidade, porque a diferença importa:

| Etapa | Estado verificado |
|---|---|
| Testes em push | automático ✓ |
| Treino em `develop` e `homolog` | automático ✓ — após a correção da propagação de `skipped` |
| Porta de qualidade em `homolog` | automática ✓ — **e está reprovando** |
| Publicação de `homolog` e `sha-<sha7>` | **não ocorre**, porque a porta reprova |
| Cálculo da versão e Release PR | automático ✓ |
| Disparo da promoção pela tag `v*` | automático ✓ — o workflow executa |
| Promoção por retag | **aborta**, por não haver candidato em `homolog` |

### A cadeia está correta e termina em bloqueio

Execução verificada em `homolog`:

```
✅ Tests (invariantes do pipeline)
✅ Train and validate model  →  treina o modelo completo
❌ Verify rubric minimums    →  precision 0.7500 < 0.80  ·  build reprovada
⏭️  Build and push images     →  não executa
```

**A esteira não publica a imagem porque foi instruída a não publicar.** A porta de
qualidade recusa um modelo que não atinge os mínimos declarados, que é exatamente o
comportamento especificado na [Spec 007](specs/007-cicd-e-versionamento.md). Sem imagem
em `homolog`, a promoção aborta — e aborta de forma explícita, em vez de promover algo
não validado.

Portanto: **a tag dispara a automação, e a automação recusa entregar.** As imagens `1.0.0`
hoje publicadas no Docker Hub foram construídas e enviadas **manualmente**, contornando a
porta.

Enquanto a precisão não atingir 0,80, a esteira não produzirá imagem de produção sozinha.
Isso é uma escolha de projeto, não um defeito, e a alternativa — afrouxar a porta — só é
defensável se a exceção for declarada explicitamente em configuração, auditável e
reversível, em vez de silenciosa.
