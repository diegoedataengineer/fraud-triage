# ADR-0016 — Versionar o modelo por Conventional Commits e release-please

**Status:** Aceita
**Data:** 2026-08-20
**Alterada por:** [ADR-0017](0017-entrega-por-artefato-executavel.md) (registro de modelos) ·
[ADR-0019](0019-registry-de-imagens.md) (Docker Hub e promoção por digest)

## Contexto

A Webaula 06 apresenta o problema de versionamento em três dimensões — código, dados e
experimentos — cobertos respectivamente por Git, DVC e MLflow, e destaca o **versionamento
semântico** como o sistema padrão de numeração. O professor coloca o ponto de forma
direta: o que se quer é **um identificador que ligue os três**, para que "reproduzir o
modelo do mês passado" deixe de ser impossível.

Um número de versão só serve se responder, sozinho, a três perguntas: qual código treinou
este modelo, sobre quais dados, e com quais hiperparâmetros e métricas. Uma versão que
não amarra isso é decoração.

Há ainda a questão de **quem decide o número**. Versão escolhida à mão diverge do
conteúdo do release: alguém esquece de subir, ou sobe errado. A alternativa é derivá-la
do histórico de commits, o que exige que os commits sejam legíveis por máquina.

O padrão já em uso pelo autor resolve isso com **Conventional Commits** validados por
commitlint e **`googleapis/release-please-action`**, que lê o histórico, calcula o próximo
número semântico, gera o CHANGELOG e cria a tag e a Release.

## Decisão

**A versão do projeto é a versão do modelo**, calculada automaticamente pelo
release-please a partir dos Conventional Commits. Não há numeração manual.

### Semântica do SemVer aplicada a ML

O ponto não é adotar `MAJOR.MINOR.PATCH`, é definir o que cada dígito significa quando o
artefato é um modelo — caso contrário a numeração é arbitrária:

| Incremento | Significado neste projeto | Commit |
|---|---|---|
| **MAJOR** | Quebra de contrato: mudam as features de entrada, o schema da API ou o significado das faixas da política | `feat!:` ou `BREAKING CHANGE:` |
| **MINOR** | Retreino com ganho de métrica, novo atributo compatível, mudança de algoritmo mantendo o contrato | `feat(model):`, `feat(features):` |
| **PATCH** | Recalibração, reajuste de limiar dentro da política vigente, correção que não altera contrato | `fix(calibration):`, `fix(policy):` |

O critério que separa MAJOR de MINOR é **o contrato**, não a magnitude do ganho: um
modelo muito melhor que consome as mesmas features é MINOR; um modelo igual que passa a
exigir uma feature nova é MAJOR, porque quebra quem o chama.

### O identificador que liga as três dimensões

Todo artefato carrega um `metadata.json` — é ele que transforma o número em rastro:

```json
{
  "version": "2.1.0",
  "git_sha": "a1b2c3d…",
  "data": { "source": "openml:1597", "sha256": "…", "n_rows": 284807 },
  "training": { "seed": 42, "hpo_trials": 50, "best_params": { }},
  "metrics": { "pr_auc": 0.0, "roc_auc": 0.0, "recall": 0.0, "precision": 0.0 },
  "policy": { "t_low": 0.0, "t_high": 0.0 },
  "environment": { "python": "3.11", "dependencies": { } }
}
```

`git_sha` amarra o código; `data.sha256` amarra os dados; `training` e `metrics` amarram
parâmetros e resultado. É a ligação das três dimensões da Webaula 06, sem exigir DVC nem
MLflow hospedado.

### O registro de modelos

As **Releases do GitHub** cumprem o papel de registro: permanentes, versionadas,
imutáveis e sem infraestrutura adicional. Cada Release `vX.Y.Z` carrega o artefato do
modelo, o `metadata.json` e o CHANGELOG do que mudou. Recuperar o modelo de qualquer
versão passada é baixar o anexo daquela Release.

O layout no repositório espelha a versão:

```
models/fraud-triage/<versão>/
    model.joblib          modelo + calibrador
    preprocessor.joblib   escalonador e definição de atributos
    policy.json           limiares da política de três faixas
    metadata.json         o identificador que liga código, dados e parâmetros
```

## Alternativas consideradas

- **Numeração manual da versão.** Controle total. Descartada por divergir do conteúdo na
  primeira distração e por não deixar rastro do motivo do incremento.
- **Versões inteiras crescentes, ao estilo TensorFlow Serving (`models/nome/1/`, `/2/`).**
  É a convenção do Google para servir modelos e é simples de operar. Descartada porque o
  número não comunica **natureza** da mudança: quem consome a API não sabe, ao ver a
  versão 7, se precisa alterar sua integração. O contrato é o que importa aqui.
- **Hash do commit como versão do modelo.** Rastreabilidade perfeita. Descartada por não
  ser ordenável nem legível: `a1b2c3d` não diz se sucede ou antecede `f4e5d6c`.
- **DVC para versionar o modelo.** É o que a Webaula 06 apresenta para dados e modelos.
  Descartada porque exige armazenamento remoto configurado, e o artefato final aqui tem
  poucos megabytes — cabe na Release, que já é versionada. O papel do DVC de amarrar dado
  a commit é cumprido pelo `data.sha256` no metadata.
- **MLflow Model Registry.** Apresentado na Webaula 06 e adequado ao papel. Descartada por
  exigir servidor para ser útil de fato; local, seria apenas um diretório com mais
  cerimônia que as Releases.

## Consequências

- A versão passa a ser consequência automática dos commits — nenhuma decisão manual, e o
  CHANGELOG sai de graça.
- **Os commits passam a ser obrigatoriamente Conventional Commits**, validados em PR. É
  disciplina imposta a cada commit; é o custo de ter versão automática.
- Um retreino sem mudança de código não gera versão nova por si só: é preciso um commit
  que o registre (`feat(model): retreina com …`). Isso é desejável — retreino silencioso
  não deveria produzir artefato promovível.
- Recuperar qualquer modelo anterior fica trivial, e o `metadata.json` permite auditar de
  onde ele veio.
- Dependemos do release-please, uma ação de terceiros. Risco baixo e contido: se
  desaparecer, a tag pode ser criada à mão sem alterar o resto da esteira.
