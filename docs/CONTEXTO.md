# Contexto do projeto

Documento de orientação para quem for trabalhar neste repositório.

Projeto de **Sistematização** da disciplina Engenharia de Aprendizado de Máquina
(turma EAM-A-CV-VIR-072626098). Vale 40 pontos, entrega em **23/08/2026 23:55**.

Enunciado completo: `../../Objetos da Sistematizacao/`. Materiais de apoio (transcrições
das webaulas, PDFs) estão nas pastas irmãs, fora deste repositório.

## O que este projeto é

Detecção de fraude em cartão de crédito (Trilha A — supervisionado), mas com uma
formulação própria: a saída do modelo não alimenta um classificador binário e sim uma
**política de triagem em três faixas** — aprovar, revisar manualmente, bloquear — sujeita
à **capacidade real de revisão manual**, sobre probabilidades **explicitamente
calibradas**.

Isso é deliberado. O professor publicou um repositório de referência no mesmo domínio
(`fraud-detection-mlops`), disponibilizado apenas **para observação**. A diferenciação
não vem de trocar o dataset — vem de mudar o objeto de otimização. Ver
[ADR-0001](adr/0001-trilha-e-dominio.md) e
[ADR-0010](adr/0010-politica-de-decisao.md).

## Antes de escrever código, leia

- [`adr/`](adr/) — **por que** cada decisão foi tomada. 14 ADRs.
- [`specs/`](specs/) — **o que** construir e como verificar. 6 specs.
- [`PLANO.md`](PLANO.md) — sequência de execução e estado atual.
- [`RUBRICA.md`](RUBRICA.md) — cada ponto da rubrica e onde ele é atendido.

Se uma decisão de implementação contrariar uma ADR, **a ADR vence** — ou se escreve uma
nova ADR que a substitua, com o motivo. Não se altera silenciosamente uma decisão
registrada.

## Invariantes que não podem ser violados

Estes não são estilo, são correção. Cada um tem teste automatizado:

1. **O particionamento é cronológico.** Nunca `train_test_split` aleatório, nunca `KFold`
   embaralhado. Fraude é adversarial e não estacionária; embaralhar vaza o futuro.
2. **Nada é ajustado no teste.** Escalonador, calibrador e limiares são estimados no
   treino ou na validação, conforme a spec. O teste é tocado **uma única vez**, ao final.
3. **Sem SMOTE ou reamostragem sintética.** O desbalanceamento é tratado por ponderação
   de classe. Ver [ADR-0006](adr/0006-desbalanceamento.md) — a justificativa é
   técnica, não preferência.
4. **Métricas da classe positiva, nunca média ponderada.** Com 0,17% de positivos, a
   média ponderada passa de 0,99 sem significar nada.
5. **Todo número reportado vem de execução real**, gravado em `reports/*.json`. Nenhum
   valor digitado à mão ou estimado — inclusive os desfavoráveis.
6. **Nenhum parâmetro fixo em código.** Tudo em `config/config.yaml`.
7. **`src/` é a fonte da verdade**; o notebook importa de `src/`, não reimplementa.
8. **Produção nunca retreina.** A esteira promove o artefato validado em `staging`. Ver
   [ADR-0015](adr/0015-esteira-de-promocao.md).
9. **A versão nunca é editada à mão.** Ela sai dos Conventional Commits via
   release-please. Ver [ADR-0016](adr/0016-versionamento-do-modelo.md).

## Fatos verificados da fonte de dados

Medidos em 2026-08-20 e codificados em `config.data.expected` — a ingestão falha se
divergirem:

- 284.807 linhas × 31 colunas (`Time`, `V1`–`V28`, `Amount`, `Class`)
- 492 fraudes → 0,1727%
- `Time` monotonicamente crescente, 48,0 horas
- 0 nulos; 1.081 duplicatas exatas (viram 9.144 se `Time` for descartada)
- `fetch_openml` **descarta `Time`** — é preciso baixar o ARFF bruto
  ([ADR-0002](adr/0002-fonte-de-dados.md))

## Convenções

- Código e identificadores em inglês; documentação, comentários e relatório em
  português.
- Cada módulo roda isolado: `python -m src.<modulo>`.
- **Conventional Commits obrigatórios**, validados em PR: `tipo(escopo): assunto`, até
  72 caracteres, sem inicial maiúscula. Escopos válidos em `.commitlintrc.json`.
  O tipo determina o incremento de versão — `feat` sobe MINOR, `fix` sobe PATCH,
  `feat!` sobe MAJOR. Commits em português, explicando o **porquê** quando não for óbvio.
- Fluxo de branches: `develop → staging → main`, com guarda na CI.
