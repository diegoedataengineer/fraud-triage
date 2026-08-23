# ADR-0029 — Uma versão só: artefato e imagem com o mesmo número

**Status:** Aceita
**Data:** 2026-08-23
**Complementa:** [ADR-0016](0016-versionamento-do-modelo.md) ·
[ADR-0019](0019-registry-de-imagens.md) · [Spec 007](../specs/007-cicd-e-versionamento.md)

## Contexto

Até a release `1.4.1`, a imagem em produção e o artefato dentro dela tinham **números
diferentes** — a imagem `1.4.1` embarcava o modelo `1.4.0`. Não era defeito: era
consequência direta da ordem dos acontecimentos na esteira.

```
homolog:  build do candidato  →  artefato carimbado com src/__init__.py  (1.4.0)
main:     release-please       →  calcula a próxima versão               (1.4.1)
tag:      promoção por retag   →  a MESMA imagem ganha a tag 1.4.1
```

O artefato é carimbado quando é construído; o número da release só é atribuído depois. E
promover é *retag do mesmo digest*, nunca reconstrução — renumerar o que está dentro
exigiria construir de novo, e a imagem promovida deixaria de ser a que passou pela
validação ([ADR-0019](0019-registry-de-imagens.md)).

A explicação é correta e estava documentada. O problema é outro: **ela precisava ser
dada**. Todo mundo que abria o console via `Modelo 1.4.0` sobre a imagem `1.4.1` e parava
para perguntar. Uma peculiaridade que exige nota de rodapé em todo lugar onde aparece é um
custo permanente, e neste caso evitável.

## Decisão

**Anunciar a versão antes de construir**, em vez de descobri-la depois.

1. `src/__init__.py` é atualizado para a versão-alvo **no mesmo commit** que segue para
   `homolog`. O candidato é construído já carimbado com ela.
2. O commit leva o rodapé `Release-As: X.Y.Z`, que obriga o release-please a produzir
   exatamente aquela versão em vez de calculá-la pelos tipos de commit.
3. A promoção segue sendo retag. Nada é reconstruído — o número apenas já estava certo
   quando a imagem nasceu.

O `.release-please-manifest.json` **não** é editado à mão: ele registra a última release
publicada, e quem o atualiza é o próprio Release PR.

O console passa a exibir a linha da imagem **apenas quando as duas divergirem**. Iguais,
seria ruído; diferentes, é exatamente o que precisa ser visto.

## Consequências

- O que se lê no console, no `/health`, no metadata e na tag do Docker Hub é o mesmo
  número. Uma pergunta a menos, e uma nota de rodapé a menos em cada documento.
- **Custo: a versão passa a ser escolhida, não derivada.** Antes bastava usar o tipo do
  commit e o release-please calculava; agora é preciso decidir o número antes e escrevê-lo
  em dois lugares — `src/__init__.py` e o rodapé `Release-As`. É um passo manual a mais no
  procedimento de release, registrado em [DEPLOY.md](../DEPLOY.md).
- Esquecer o pré-anúncio não quebra nada: a esteira publica normalmente e os números
  voltam a divergir naquela release. O console mostra a divergência sozinho, que é o
  sinal de que o passo faltou.
- A verificação de que a promoção não reconstrói **não depende mais de comparar números**,
  e sim do digest e do `git_sha` no metadata — que era o elo confiável desde o início.

## Alternativas consideradas

- **Reconstruir a imagem depois da tag, com o número certo.** Resolveria em uma linha e
  destruiria a garantia central da esteira: a imagem entregue deixaria de ser a validada.
- **Injetar a versão na promoção, via variável ou rótulo.** Não altera o metadata gravado
  dentro do artefato, então `/health` continuaria divergindo do que o modelo diz de si.
- **Deixar como estava e explicar.** Foi o que se fez até a `1.4.1`. Funciona, e cobra a
  explicação toda vez — no README, no relatório, no roteiro do vídeo e ao vivo.
- **Derivar a versão do `git_sha`, sem semver.** Honesto e ilegível: `sha-57e7f58` não diz
  se houve quebra de compatibilidade, que é a informação que a versão existe para dar.
