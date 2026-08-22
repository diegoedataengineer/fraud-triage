# ADR-0019 — Publicar as imagens no Docker Hub, promovendo por digest

**Status:** Aceita
**Data:** 2026-08-21
**Altera:** [ADR-0016](0016-versionamento-do-modelo.md) (registro de modelos) ·
[ADR-0017](0017-entrega-por-artefato-executavel.md) (destino da imagem)

## Contexto

A ADR-0017 estabeleceu a imagem como artefato de entrega e a ADR-0016 apontava o
`ghcr.io` como registro, por autenticar com o `GITHUB_TOKEN` que a esteira já possui.

Duas razões deslocam a escolha. O **Docker Hub é o registro padrão do Docker**: um
`docker run diegodataengineer/fraud-triage:1.4.1` funciona sem configurar registro,
sem autenticar e sem que o avaliador precise conhecer o `ghcr.io` — e o atrito de quem
vai testar é critério de projeto aqui, não detalhe. Além disso, imagens em `ghcr.io`
herdam visibilidade do repositório e exigem passo extra para ficarem públicas, o que
adiciona uma forma silenciosa de a entrega falhar.

Há também a separação de responsabilidades entre **treinar** e **servir**. A imagem de
treino carrega Optuna, SHAP, matplotlib e o dataset; a de serving precisa do modelo e do
que responde uma requisição. Uma imagem só levaria ferramental de laboratório para
dentro do que roda em produção — mais superfície e imagem muito maior, sem ganho.

## Decisão

Publicar **duas imagens** no Docker Hub, construídas de um `Dockerfile` multi-stage:

| Imagem | Papel |
|---|---|
| `diegodataengineer/fraud-triage-trainer` | executa o pipeline e produz o artefato |
| `diegodataengineer/fraud-triage` | serve inferência, com o modelo embutido |

### Marcação por estágio

```
develop      →  dev-<sha7>                      descartável, retorno rápido
homolog      →  homolog  e  sha-<sha7>          este digest é o candidato à promoção
tag vX.Y.Z   →  X.Y.Z, X.Y, X, latest           retag do digest validado
```

### A promoção é retag, nunca rebuild

Na tag, a esteira **não reconstrói**. Ela usa `docker buildx imagetools create` para
apontar as tags semânticas ao **digest exato** que passou pela validação em `homolog`.

Isso não é otimização, é correção. Reconstruir a partir do mesmo commit produz uma
imagem diferente — camadas com outros timestamps, dependências transitivas resolvidas em
outro instante — e a imagem que iria a produção não seria a que foi validada. É
exatamente o que a ADR-0015 existe para impedir, agora aplicado ao contêiner inteiro.

O `metadata.json` continua sendo o identificador que liga código, dados e parâmetros
(ADR-0016), e viaja dentro da imagem.

## Alternativas consideradas

- **`ghcr.io`.** Zero segredo a configurar e imagem junto do código. Descartada pelo
  atrito de quem avalia: exige tornar o pacote público separadamente, e é registro menos
  familiar fora do GitHub.
- **Imagem única para treino e serving.** Um `Dockerfile` mais simples. Descartada por
  levar dependências de laboratório à produção e inflar a imagem servida.
- **Imagem sem o modelo, baixando o artefato na inicialização.** Deixaria a imagem
  genérica e o modelo intercambiável. Descartada por quebrar a imutabilidade: o que roda
  passaria a depender do que estivesse no armazenamento naquele momento, e a imagem
  deixaria de ser o artefato promovido.
- **Reconstruir a imagem na tag.** É o que a maioria das esteiras faz. Descartada porque
  o binário promovido deixaria de ser o validado.

## Consequências

- Testar o modelo passa a ser um comando, sem clone e sem credencial.
- Passam a existir **dois segredos** a manter (`DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`),
  onde o `ghcr.io` não exigiria nenhum. É o custo aceito pela redução de atrito.
- A imagem de serving só pode ser construída **depois** do treino, porque embute o
  artefato — o que cria dependência entre etapas da esteira.
- O Docker Hub aplica limite de download por IP em contas gratuitas. Irrelevante na
  escala desta avaliação, mas registrado.
- Promover uma versão passa a ser uma operação de metadados, em segundos, sem executar
  build.
