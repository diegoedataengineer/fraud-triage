# ADR-0015 — Adotar o fluxo `develop → staging → main` com promoção de artefato

**Status:** Aceita
**Data:** 2026-08-20

## Contexto

A Webaula 06 trata modelo como aplicação — "trate-o como se fosse uma aplicação" — e
cobra versionamento, reprodutibilidade e automação (CI/CD, CT, CM). Um modelo que chega
à produção por caminho diferente do que foi validado não tem garantia nenhuma: o que se
testou não é o que se serve.

O problema específico de ML é que **retreinar é não determinístico o bastante para
importar**. Se cada estágio da esteira roda o treino de novo, o modelo validado em
homologação não é o mesmo binário que entra em produção — mesmo com semente fixa, basta
uma diferença de versão de biblioteca ou de ordem de leitura de dados. Toda a validação
passa a valer para um artefato que foi descartado.

Já existe um padrão estabelecido e em uso nos projetos do autor
(`spectrium-hub-system-web`), com fluxo de três branches, guarda de fluxo por CI,
Conventional Commits e release automatizado. Reaproveitá-lo é preferível a inventar outro:
é conhecido, está em produção e reduz a chance de erro sob prazo curto.

## Decisão

Adotar o fluxo de três branches, com uma guarda de CI que recusa PRs fora dele:

```
feat/* fix/* chore/* ...  ──▶  develop  ──▶  staging  ──▶  main  ──▶  tag vX.Y.Z
                                  │             │                        │
                             CI rápida     CI completa              promove o
                             (HPO reduzido) treina e publica       artefato validado
                                            o artefato do modelo   (NÃO retreina)
```

**Princípio central: treina uma vez, promove o artefato.** A produção **não executa
`run_pipeline.py`**. Ela recupera o artefato que a esteira de `staging` treinou e
validou, confere a procedência e o publica na Release. Se o artefato não for encontrado,
o job **falha** — jamais retreina para "resolver".

Responsabilidade de cada estágio:

| | `develop` | `staging` | `main` / tag |
|---|---|---|---|
| Testes e lint | sim | sim | sim |
| Treina o modelo | sim, HPO reduzido | sim, HPO completo | **não** |
| Valida mínimos da rubrica | não bloqueia | **bloqueia** | reconfere no metadata |
| Publica artefato do modelo | não | sim | promove para a Release |

A verificação de procedência é objetiva: o `git_sha` gravado no `metadata.json` do
artefato precisa ser **ancestral da tag** que está sendo publicada. Isso é checável com
`git merge-base --is-ancestor` e impede que um artefato de outra linhagem seja promovido.

## Alternativas consideradas

- **Branch única com deploy no push.** Simples e rápido. Descartada por não ter estágio
  de validação: um treino ruim vai direto a produção.
- **`dev`/`hom`/`prod`, como no repositório de referência da disciplina.** Equivalente em
  mérito. Descartada por divergir do padrão já em uso pelo autor, sem ganho — a
  nomenclatura `develop`/`staging`/`main` é a convencional e é a que a esteira existente
  já implementa.
- **Retreinar em cada estágio.** Garante que cada ambiente treina com seu próprio dado.
  Descartada por destruir a garantia de que o modelo validado é o modelo servido — que é
  a razão de existir da esteira.
- **Model Registry gerenciado (SageMaker, Vertex AI, MLflow hospedado).** É o que se usaria
  em produção real. Descartada por exigir infraestrutura e credenciais que o projeto não
  tem; o papel de registro é cumprido pelas Releases do GitHub (ADR-0016), que são
  permanentes e versionadas.

## Consequências

- O modelo servido é, comprovadamente, o mesmo binário validado — que é o ponto.
- O deploy de produção é **simulado**: sem conta em nuvem, o job sobe a API localmente,
  consulta `/health`, executa a demonstração e encerra. Isso é declarado no relatório;
  apresentá-lo como deploy real seria falso.
- A guarda de fluxo pode atrapalhar correções urgentes. Aceito: `hotfix/*` entra por
  `staging` como qualquer outra branch.
- Passa a haver dependência entre execuções de workflow (produção lê artefato de
  `staging`). É acoplamento real, mitigado pela verificação de ancestralidade e por falha
  explícita quando o artefato não existe.
