# ADR-0018 — Persistir o estado operacional em PostgreSQL

**Status:** Aceita
**Data:** 2026-08-21
**Altera:** [ADR-0017](0017-entrega-por-artefato-executavel.md) (composição do ecossistema)

## Contexto

O ciclo de vida completo exige etapas que **não cabem em um processo sem estado**. Três,
especificamente, foram desenhadas nas ADRs anteriores mas não tinham onde existir:

1. **A fila de revisão manual** (ADR-0010) é a faixa do meio da política. Uma fila que
   vive em memória some quando o contêiner reinicia, e sem persistência não há como
   atribuir caso a analista, medir tempo de resposta ou respeitar capacidade.
2. **O rótulo atrasado por chargeback** (ADR-0014) chega semanas depois da decisão. Isso
   é, por definição, um registro que precisa sobreviver ao processo que o originou.
3. **O histórico de drift** só informa como série temporal. Um PSI isolado não diz nada;
   a trajetória dele é que dispara retreino.

Uma solução anterior considerou SQLite embutido no contêiner. Funciona para demonstração,
mas não representa a arquitetura real: não suporta concorrência de escrita relevante, não
separa o estado do contêiner e não permite que API e monitor compartilhem o mesmo banco.

## Decisão

Adotar **PostgreSQL como banco operacional**, subindo como serviço no `docker compose`
do ecossistema, com schema versionado em `db/schema.sql`.

A conexão é **opcional por configuração**, e essa escolha preserva os dois caminhos de
uso da ADR-0017:

| Caminho | `DATABASE_URL` | Comportamento |
|---|---|---|
| `docker run` da imagem, sozinho | ausente | API responde inferência normalmente, sem persistir. Caminho de menor atrito para avaliar o modelo. |
| `docker compose up` | presente | Ecossistema completo: decisões gravadas, fila de revisão ativa, drift acumulado. |

Degradar sem banco em vez de falhar é deliberado: o modelo é o objeto avaliado, e exigir
banco para responder uma inferência tornaria a avaliação mais frágil sem tornar o modelo
melhor.

Escolhemos Postgres em contêiner, e não um serviço gerenciado, porque o ecossistema
precisa subir sem conta, sem credencial e sem custo — condição para o professor exercitar
o fluxo em qualquer máquina com Docker.

## Alternativas consideradas

- **SQLite embutido.** Zero infraestrutura e mantém o `docker run` único. Descartada por
  não representar a arquitetura real e por não permitir que API e monitor compartilhem
  estado, que é o ponto de ter as três camadas de monitoramento.
- **Supabase gerenciado.** Traria Postgres, autenticação, tempo real e um caminho pronto
  para o console do analista. Descartada pelo prazo: exige provisionar projeto, e o
  esforço sairia do que é avaliado — o modelo — a dois dias da entrega. A modelagem de
  dados aqui é compatível com Postgres gerenciado, então migrar depois é direto.
- **Apenas arquivos JSON em disco.** É o que as ADRs 0013 e 0016 já fazem para métricas e
  metadados. Descartada para estado operacional por não ter transação, índice nem consulta
  — a fila de revisão precisa das três.

## Consequências

- O ciclo de vida deixa de ter lacuna: coleta de rótulo, fila de revisão e histórico de
  drift passam a ter lugar próprio, e retreino passa a ser disparável por consulta.
- O ecossistema ganha um serviço a orquestrar e um schema a versionar.
- **Dois modos de execução precisam ser testados**, não apenas um: com e sem banco. Sem
  isso, o caminho sem banco quebra silenciosamente.
- A imagem da API permanece sem estado, o que mantém válida a promoção por retag da
  ADR-0017.
