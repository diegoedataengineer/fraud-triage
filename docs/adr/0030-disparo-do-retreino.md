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

### Carência entre retreinos

Disparar e retreinar são coisas diferentes. Os gatilhos são reportados como estão, mas a
**decisão** respeita uma carência de `min_retrain_interval_days` (7).

Isso não é detalhe: sem ela, o agendador diário mandaria retreinar **todo dia**. O PSI
apurado sobre treino × teste dispara sempre, porque aquele deslocamento é fixo — e um
sinal contínuo não justifica ação contínua. Ele diz que o mundo mudou uma vez, não que
mudou de novo a cada verificação.

Foi um defeito de projeto encontrado **executando o workflow**, não revisando-o: a
primeira versão teria disparado retreino diariamente, que é a mesma patologia do controle
que aciona sempre criticada no [ADR-0027](0027-porta-da-esteira.md).

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

## O limite que nenhum código resolve

**Não há dados novos para o retreino colher.**

`src/ingestion.load_raw()` lê sempre a mesma fonte pública e fixa: 284.807 transações de
48 horas, do OpenML. Não existe ingestão incremental. E como o treino é determinístico
([ADR-0023](0023-hiperparametros-travados.md)), retreinar sobre dados idênticos produz um
modelo **bit a bit idêntico**.

Vale dizer isso sem rodeio: o mecanismo de disparo está completo e a fonte é que não
renova. Disparar retreino aqui é exercitar a cadeia, não melhorar o modelo.

Num sistema real, o retreino consumiria transações de produção com rótulo por chargeback.
E aqui a distância é menor do que parece — **a matéria-prima já é coletada**. O PostgreSQL
registra cada transação com as 28 componentes, `Time` e `Amount` em JSONB, mais a decisão
com os limiares vigentes e a versão do modelo. Numa execução de demonstração:

```
transações   902     decisões   902     chargebacks   0
```

Faltam **duas** coisas, não uma:

1. **O rótulo.** A tabela `chargebacks` existe e está vazia, porque o chargeback vem do
   titular contestando a cobrança, semanas depois — e só para o que não foi bloqueado. As
   177 transações bloqueadas daquela amostra nunca gerarão um: o modelo interfere na
   coleta do rótulo que serviria para avaliá-lo ([ADR-0014](0014-monitoramento.md)).
2. **O pipeline lendo do banco.** `src/ingestion.load_raw()` lê o ARFF fixo e nada mais.
   Passar a compor o conjunto de treino com transações rotuladas do banco é código que não
   existe.

A segunda é trabalho; a primeira é o mundo. É por isso que a carência e a distinção entre
disparar e promover importam mesmo aqui: são as partes da decisão que continuam corretas
quando a fonte de dados passar a existir.

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
