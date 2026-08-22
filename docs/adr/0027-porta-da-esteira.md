# ADR-0027 — Separar a porta da esteira dos mínimos da rubrica

**Status:** Aceita
**Data:** 2026-08-22
**Complementa:** [ADR-0015](0015-esteira-de-promocao.md) (promoção de artefato) ·
[Spec 007](../specs/007-cicd-e-versionamento.md)

## Contexto

A porta de qualidade em homologação recusava toda build, e com razão: a precisão obtida é
**0,7800** e o mínimo da rubrica é **0,80**. Build reprovada não publica imagem, e sem
imagem em `homolog` a promoção em tag aborta por falta de candidato.

A consequência prática foi pior que o bloqueio em si. As versões `1.0.0` e `1.1.0` no
Docker Hub acabaram sendo **construídas e enviadas à mão**, contornando a esteira. Ou
seja: a automação existia, recusava-se a publicar, e o trabalho seguia por fora dela — que
é exatamente o comportamento que uma esteira existe para impedir.

A saída óbvia seria baixar `evaluation.rubric_minimums.precision` para 0,75. E seria
errada, porque esse valor não alimenta apenas a porta. Ele é consumido em quatro lugares:

| Consumidor | Efeito de baixá-lo |
|---|---|
| `src/train.py` | o objetivo do tuning passa a mirar precisão menor ([ADR-0021](0021-objetivo-do-tuning.md)) |
| `src/model_selection.py` | a comparação entre candidatos muda de alvo |
| `src/evaluate.py` | o ponto de operação é escolhido para outro patamar |
| `src/verify_minimums.py` | a porta da esteira |

Baixar o número **retreinaria o modelo** para um alvo menor e faria o relatório afirmar
que os mínimos foram atingidos quando o enunciado exige 0,80. Não é afrouxar uma porta —
é falsear o resultado.

## Decisão

Separar dois conceitos que estavam colapsados num único valor:

**`evaluation.rubric_minimums`** — o requisito do enunciado. Define o que se reporta como
atingido e alimenta tuning, seleção e ponto de operação. **Permanece em 0,80** e não é
ajustável por conveniência.

**`evaluation.ci_gate`** — o que reprova uma build em homologação. Consumido **apenas**
por `src/verify_minimums.py`. A precisão fica em **0,75**, declarada como exceção com o
motivo ao lado, na própria configuração.

A saída da verificação anuncia a diferença:

```
✅ precision  0.7800 ≥ 0.75  (exceção — rubrica exige 0.80)
```

Isso é deliberado. Uma build aprovada por exceção não pode parecer uma build que atingiu o
requisito — quem lê o log da esteira precisa ver a distinção sem procurar por ela.

O relatório continua reportando `0,78 contra 0,80` como **não atingido**. Afrouxar a porta
libera a entrega; não muda o resultado.

## Alternativas consideradas

- **Baixar `rubric_minimums` para 0,75.** Um único valor, mais simples. Descartada por
  retreinar o modelo para outro alvo e por fazer o relatório afirmar algo falso sobre o
  requisito.
- **Manter a porta em 0,80 e publicar as imagens à mão.** Preserva o rigor formal.
  Descartada porque era o estado de fato, e ele é pior: a esteira vira teatro enquanto o
  trabalho real acontece por fora, sem rastro e sem verificação.
- **Remover a porta.** Simplificaria. Descartada — a porta pega regressões reais; o
  problema era o valor único, não a existência dela.
- **Marcar a build como instável em vez de reprovar.** O GitHub Actions não tem esse
  estado de forma nativa, e emular com `continue-on-error` esconderia a exceção em vez de
  declará-la.

## Consequências

- A esteira volta a produzir imagem sozinha, e a promoção em tag passa a ter candidato.
  O caminho automático deixa de ser contornado.
- A exceção fica em **uma linha de configuração**, versionada e revisável em diff. Voltar
  a 0,80 é apagar um número.
- Passam a existir dois valores que precisam ser lidos juntos. O risco é alguém consultar
  só um deles; mitigado pelo comentário em ambos e pela anotação na saída da verificação.
- Fica registrado o padrão de falha que motivou tudo isso: **um controle rígido demais não
  produz mais rigor, produz contorno.** A porta em 0,80 não impediu que versões fossem
  publicadas — impediu apenas que fossem publicadas *pela esteira*.
