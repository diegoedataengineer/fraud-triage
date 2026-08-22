# ADR-0017 — Entregar um ecossistema executável em vez de um notebook

**Status:** Aceita
**Data:** 2026-08-21
**Alterada por:** [ADR-0018](0018-persistencia-operacional.md) (composição do ecossistema) ·
[ADR-0019](0019-registry-de-imagens.md) (destino da imagem)
**Altera:** [ADR-0012](0012-fonte-da-verdade.md) (papel do notebook) ·
[ADR-0016](0016-versionamento-do-modelo.md) (registro de modelos)

## Contexto

O enunciado escrito descreve a entrega como um PDF contendo o notebook do Colab
executado. Em **aula presencial, o professor autorizou a entrega do artefato**, o que
abre a possibilidade de entregar a solução na forma em que ela realmente roda.

Isso muda o alvo. Um notebook demonstra que o código executou **uma vez, na máquina de
quem o executou**. Um artefato executável demonstra que o modelo roda **em qualquer
máquina, incluindo a do avaliador** — que é a definição prática de reprodutibilidade que
a disciplina cobra.

A Webaula 06 trata reprodutibilidade em três camadas — ambiente virtual, dependências
travadas e **Docker** — e coloca a conteinerização como a camada que resolve o problema
de "na minha máquina funciona". A ADR-0013 já cobria as duas primeiras; faltava a
terceira, e ela era inalcançável enquanto o Colab fosse o ambiente de execução.

O objetivo declarado passa a ser: **o professor precisa conseguir exercitar o fluxo
inteiro**, não apenas ler um resultado.

## Decisão

Entregar um **ecossistema executável**, com dois caminhos de uso deliberadamente
distintos:

**1. Caminho rápido — sem clonar nada.** Uma imagem publicada, versionada, que sobe a
API de inferência com o modelo embutido:

```
docker run -p 8000:8000 ghcr.io/<owner>/fraud-triage:<versão>
```

Em seguida, `http://localhost:8000/docs` oferece o Swagger para submeter transações e
observar a decisão da política de três faixas com a explicação SHAP correspondente.

**2. Caminho completo — o ecossistema.** `docker compose up` sobe o conjunto: a API, a
interface do MLflow com os experimentos registrados, o relatório de drift e um executor
de demonstração. É onde o fluxo pode ser inspecionado etapa a etapa.

Além disso, `make train` reexecuta o pipeline inteiro **dentro do contêiner**, a partir
da fonte pública, e reproduz as métricas do relatório. É esta a demonstração de
reprodutibilidade que substitui a reexecução do notebook — e é mais forte, porque não
depende do ambiente do avaliador.

### O que muda nas ADRs anteriores

- **ADR-0012** continua valendo no essencial: `src/` é a fonte da verdade. O que muda é o
  papel do notebook, que deixa de ser o veículo de entrega. Ele permanece opcional, como
  material de apoio ao relatório, sem ser o caminho de execução.
- **ADR-0016** muda o registro de modelos: em vez das Releases do GitHub, o registro
  passa a ser o **container registry** (`ghcr.io`). A versão calculada pelo
  release-please vira a **tag da imagem**, e promover para produção é **retag** da imagem
  já validada — nunca rebuild. O `metadata.json` continua sendo o identificador que liga
  código, dados e parâmetros, e viaja dentro da imagem.

O princípio da ADR-0015 fica mais forte, não mais fraco: o artefato promovido deixa de
ser apenas o modelo serializado e passa a ser **o ambiente inteiro** — modelo,
calibrador, limiares, dependências e runtime. Não há mais espaço para divergência entre
o que foi validado e o que roda.

## Alternativas consideradas

- **Manter o notebook como entrega principal.** É o que o enunciado escrito descreve.
  Descartada porque a autorização em aula permitiu algo melhor, e porque o notebook prova
  menos: demonstra uma execução, não a capacidade de executar.
- **Entregar os dois com peso igual.** Seria o mais seguro quanto à rubrica. Descartada
  por diluir o esforço a dois dias do prazo, com o pipeline ainda por escrever. O
  notebook permanece possível como material de apoio se sobrar tempo.
- **Publicar a imagem no Docker Hub.** Mais conhecido. Descartada por exigir conta e
  credencial extra; o `ghcr.io` é gratuito, autentica com o próprio `GITHUB_TOKEN` da
  esteira e mantém imagem e código no mesmo lugar.
- **Entregar apenas o `docker compose`, sem imagem publicada.** Exigiria clonar e
  construir. Descartada porque o caminho de menor atrito para o avaliador é um único
  `docker run`, sem clone e sem build.

## Consequências

- A reprodutibilidade passa a ser demonstrável em qualquer máquina com Docker, sem
  depender de sessão do Colab, de disponibilidade de GPU ou da imagem-base que o Google
  mantiver naquele dia.
- A terceira camada de reprodutibilidade da Webaula 06 passa a estar coberta.
- **Surge uma dependência nova para o avaliador: ele precisa ter Docker.** É risco real e
  aceito; mitigado pelo relatório trazer todos os resultados, de modo que a execução seja
  verificação e não pré-requisito de leitura.
- A esteira ganha uma etapa de build e publicação de imagem, e passa a exigir
  `packages: write` nas permissões.
- O relatório continua sendo o entregável que carrega os números. O ecossistema é o que
  permite conferi-los.
