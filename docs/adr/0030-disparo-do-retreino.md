# ADR-0030 — O monitoramento dispara o retreino, e não a promoção

**Status:** Aceita
**Data:** 2026-08-23
**Complementa:** [ADR-0014](0014-monitoramento.md) · [ADR-0015](0015-esteira-de-promocao.md) ·
[Spec 005](../specs/005-monitoramento.md)

## Contexto

Os três gatilhos de retreino estavam definidos desde o [ADR-0014](0014-monitoramento.md):
PSI acima de 0,25 nos dez atributos mais influentes, queda de 10 pontos na precisão da
fila de revisão, e agenda de 30 dias.

Definidos, não implementados. Ao verificar o que existia de fato:

| Gatilho | Situação até a `1.5.0` |
|---|---|
| PSI | **calculado** e gravado em `reports/drift_report.json` |
| Queda de precisão na revisão | apenas em `config.yaml` — **zero usos em código** |
| Agenda de 30 dias | apenas em `config.yaml` — **zero usos em código** |

E o mais relevante: **ninguém consumia o resultado**. O campo `triggered` era produzido e
ficava parado. Nenhum workflow, serviço ou alerta o lia. Um monitoramento que mede e não
age não é monitoramento — é um relatório.

## Decisão

**`monitoring/check_triggers.py`** avalia os três e devolve um veredito. Cada gatilho
declara a própria disponibilidade de dado, e há **três estados**, não dois:

- `disparou` — o limiar foi cruzado;
- `estável` — foi avaliado e está dentro do limite;
- `sem dados` — não foi possível avaliar.

A distinção entre os dois últimos é o ponto. Chamar de estável um gatilho que não foi
verificado afirma algo que ninguém apurou, e é assim que um monitoramento passa a dar
falsa segurança.

**`.github/workflows/retrain.yml`** roda diariamente, avalia, e **dispara a esteira em
`homolog`** quando algum gatilho acusa. A frequência da verificação é independente do
limiar: a agenda é de 30 dias, mas só se descobre que venceu verificando com mais
frequência que isso.

Retreinar não é um modo especial: é a mesma esteira executando de novo, com a mesma porta
de qualidade. Por isso o agendador chama `ci.yml` em vez de ter pipeline próprio.

### O que o disparo não faz

**Não promove.** Um gatilho produz candidato em homologação; publicar em produção continua
exigindo que uma pessoa mescle o Release PR.

Isso é deliberado. Um gatilho de drift diz que o mundo mudou — não que o modelo novo é
melhor. Promover automaticamente trocaria um risco conhecido, o modelo atual envelhecendo,
por um desconhecido: um modelo recém-treinado sobre dados possivelmente contaminados pela
própria mudança que disparou o alarme. Em detecção de fraude, onde o rótulo chega semanas
depois e é enviesado por seleção ([ADR-0014](0014-monitoramento.md)), o erro levaria
semanas para aparecer.

## Consequências

- Os três gatilhos passam a ser avaliáveis por comando, com saída legível e JSON.
- O gatilho de precisão da revisão só existe onde há banco: sem `DATABASE_URL` não há
  série para comparar, e ele responde `sem dados`.
- O PSI hoje é apurado sobre **treino × teste**, não sobre tráfego de produção contra a
  referência de treino. É a demonstração do mecanismo sobre os dados que existem, e
  confirma que a base é não estacionária — mas não é sinal de produção, e o próprio campo
  `origem` diz isso. Fechar essa distância exigiria acumular tráfego real, que este
  trabalho não tem.
- A idade do modelo vem da data da última release, já que o artefato não é versionado
  ([ADR-0016](0016-versionamento-do-modelo.md)).
- Fica um custo: um workflow diário que quase sempre não faz nada. É barato, e a
  alternativa — verificar a cada 30 dias — descobriria o vencimento com até 30 dias de
  atraso.

## Alternativas consideradas

- **Reprovar a build quando o PSI dispara.** Seria o erro do [ADR-0027](0027-porta-da-esteira.md)
  de novo: o PSI apurado hoje dispara sempre, porque o deslocamento entre treino e teste é
  inerente a esta base — é justamente o que justifica o split cronológico. Uma porta que
  reprova sempre não produz rigor, produz contorno.
- **Promover automaticamente após o retreino.** Descartada pelo motivo acima: o gatilho
  informa que o mundo mudou, não que o modelo novo é melhor.
- **Deixar como estava, especificado e não implementado.** Honesto se declarado, e era o
  que o README declarava. Mas a distância entre "especificado" e "funcionando" era de um
  arquivo, e mantê-la seria escolher a documentação em vez do sistema.
