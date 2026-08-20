# ADR-0011 — Usar SHAP como técnica principal de explicabilidade

**Status:** Aceita
**Data:** 2026-08-20

## Contexto

A rubrica reserva 5 pontos à explicabilidade e exige ao menos uma técnica. Mais do que a
rubrica, há duas necessidades reais no domínio: o analista que recebe uma transação na
faixa de revisão manual (ADR-0010) precisa saber **por que** ela foi encaminhada, e a
área de risco precisa entender o comportamento agregado do modelo antes de autorizar
bloqueios automáticos.

Existe uma limitação incontornável a enfrentar de frente: `V1`–`V28` são **componentes de
PCA anonimizados**. Nenhuma técnica de explicabilidade pode dizer o que `V14`
significa em termos de negócio, porque essa informação foi destruída na anonimização do
dataset original. Qualquer relatório que atribua sentido semântico a essas variáveis está
inventando. Apenas `Amount` e `Time` são diretamente interpretáveis.

## Decisão

Adotar **SHAP** como técnica principal, via `TreeExplainer` — exato e eficiente para
modelos de árvore, sem a aproximação por amostragem do explicador genérico.

Três níveis de leitura, cada um com propósito distinto:

1. **Global** — `summary_plot` sobre amostra do teste: quais variáveis mais movem o
   modelo e em que direção.
2. **Local** — `waterfall` para casos individuais: uma fraude detectada, um falso
   positivo e um falso negativo. Os dois últimos são os mais informativos, e são
   justamente os que costumam ser omitidos.
3. **Operacional** — explicação de uma transação na faixa de revisão manual, no formato
   que apoiaria a decisão do analista. É o que liga explicabilidade a operação.

Como verificação cruzada, confrontamos o ranking do SHAP com duas fontes independentes:
os **coeficientes da regressão logística** (ADR-0007) e a **importância por ganho** do
XGBoost. Convergência reforça a conclusão; divergência é discutida em vez de escondida.

A limitação de interpretabilidade das componentes de PCA é declarada explicitamente no
relatório. Discutimos o que **é** possível afirmar — quais componentes carregam sinal,
como `Amount` interage com o risco, se o modelo depende de `Time` de forma preocupante
para generalização — em vez de fabricar narrativas de negócio.

## Alternativas consideradas

- **LIME.** Aproximação linear local, agnóstica a modelo. Descartada como técnica
  principal por produzir explicações instáveis entre execuções (depende de amostragem
  aleatória) e por ser menos fundamentada que os valores de Shapley. Cabe como
  complemento se houver tempo.
- **Apenas `feature_importance` do modelo.** Barata e aceita pela rubrica. Descartada como
  técnica principal: a importância por ganho é enviesada a favor de variáveis de alta
  cardinalidade, é apenas global e não tem sinal direcional. Fica como verificação
  cruzada.
- **Importância por permutação.** Boa medida global e agnóstica a modelo. Descartada como
  principal por não oferecer explicação local — que é justamente o que o analista de
  revisão manual precisa.
- **Explicação contrafactual.** Muito adequada à decisão operacional. Descartada pelo
  prazo; registrada como trabalho futuro no relatório.

## Consequências

- Ganhamos explicação local e global com base teórica sólida e sinal direcional.
- O cálculo do SHAP sobre 284 mil linhas é caro; usamos amostra estratificada do teste,
  com tamanho declarado em configuração e semente fixa para reprodutibilidade.
- Uma dependência a mais (`shap`), historicamente sensível a versões de `numpy`. Reforça
  a necessidade de travar versões (ADR-0013).
- Assumimos publicamente o limite de interpretabilidade imposto pelo PCA. Tratado como
  análise crítica honesta — que é o que a rubrica de fato recompensa — e não como falha.
