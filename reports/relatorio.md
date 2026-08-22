# Triagem de Fraude em Transações de Cartão de Crédito

### Projeto de Engenharia e Operacionalização de Machine Learning

**Disciplina:** Engenharia de Aprendizado de Máquina
**Autor:** Diego Nunes de Morais
**Data:** 22 de agosto de 2026
**Trilha:** A — Aprendizado Supervisionado (classificação binária)

**Repositório:** `github.com/diegoedataengineer/fraud-triage`
**Imagem publicada:** `diegodataengineer/fraud-triage:0.1.0`

---

## 1. Introdução

Este documento descreve o desenvolvimento de uma solução completa de detecção de fraude
em transações de cartão de crédito, do dado bruto ao serviço em execução. O escopo cobre
ingestão, análise exploratória, preparação, modelagem, validação, calibração,
explicabilidade, empacotamento e monitoramento.

A entrega é um **ecossistema executável**, não um relatório de experimento. Um único
comando reproduz o serviço na máquina de quem avalia:

```bash
docker run -p 8000:8000 diegodataengineer/fraud-triage:0.1.0
```

Duas escolhas orientaram todo o trabalho e explicam boa parte dos resultados adiante.

A primeira é **medir o desempenho realizável, não o desempenho aparente**. Fraude é um
fenômeno adversarial e não estacionário: um modelo é sempre treinado no passado e
aplicado ao futuro. Por isso o particionamento é cronológico, e não aleatório. A decisão
custa alguns pontos de métrica e é a razão de este relatório apresentar números menores
que a maior parte da literatura sobre esta base.

A segunda é **tratar a saída do modelo como insumo de uma decisão operacional**, não como
um veredito binário. Nenhuma operação antifraude só bloqueia ou libera: existe uma fila
de revisão manual, ela é o instrumento central da operação, e ela é finita.

Todas as decisões de projeto estão registradas em 23 ADRs (`docs/adr/`), com o contexto,
as alternativas descartadas e o motivo de cada descarte. **Todo número neste relatório
vem de execução real**, gravado em `reports/*.json`, incluindo os desfavoráveis.

---

## 2. Descrição do problema

Detectar transações fraudulentas em tempo de autorização, sob três restrições que
definem o problema:

**Desequilíbrio extremo.** 0,1727% das transações são fraude — uma para cada 577
legítimas. Um classificador que preveja "legítima" para tudo acerta 99,83% e não detecta
nada. Acurácia é métrica inútil aqui.

**Custos assimétricos.** Deixar passar uma fraude custa o valor da transação. Bloquear
uma transação legítima custa atrito com o cliente, atendimento e risco de perdê-lo. São
grandezas diferentes, e tratá-las como iguais — que é o que otimizar F1 faz
implicitamente — é uma premissa econômica errada, apenas não declarada.

**Rótulo atrasado.** O rótulo verdadeiro não existe no momento da decisão. Ele chega
quando o titular contesta a cobrança, dias ou meses depois. Isso torna o recall
inobservável em tempo real e condiciona toda a estratégia de monitoramento (seção 10).

---

## 3. Dataset utilizado

**Credit Card Fraud Detection** (MLG-ULB), transações de cartões europeus em setembro de
2013, obtido do **OpenML** (data id 1597), de licença pública e sem autenticação.

| Característica | Valor |
|---|---|
| Transações | 284.807 |
| Atributos | 31 — `Time`, `V1`–`V28`, `Amount`, `Class` |
| Fraudes | 492 (**0,1727%**) |
| Razão de classes | 1:577 |
| Janela | 48,0 horas contíguas |
| Valores nulos | 0 |
| Duplicatas exatas | 1.081 |
| Perda total por fraude | R$ 60.127,97 |

`V1`–`V28` são componentes principais obtidas por PCA sobre os atributos originais, que
foram anonimizados por confidencialidade. `Time` e `Amount` preservam o significado
original.

### 3.1 Uma armadilha na origem dos dados

A forma usual de carregar esta base em Python é `sklearn.datasets.fetch_openml`. Ela
**descarta silenciosamente a coluna `Time`**: o OpenML a marca como atributo ignorado em
seus metadados, e o scikit-learn respeita a marcação mesmo ao devolver o frame completo.
Não há erro nem aviso — a coluna simplesmente não aparece.

Como todo o particionamento deste projeto depende de `Time`, usar a API padrão
inviabilizaria a decisão metodológica central. A ingestão baixa o **ARFF bruto** e o
interpreta diretamente, recuperando as 31 colunas. A etapa valida a fonte contra dez
critérios antes de liberar o dado adiante, e **falha com erro** se algum divergir — dado
errado que passa em silêncio produz um modelo treinado sobre outra coisa.

### 3.2 Análise exploratória

![Desequilíbrio](figures/00a_desequilibrio_classes.png)

O achado mais contraintuitivo da exploração está nos valores:

| | Mediana | Média |
|---|---|---|
| Fraudes | **R$ 9,25** | R$ 122,21 |
| Legítimas | R$ 22,00 | R$ 88,29 |

**A fraude típica é de valor mais baixo que a transação legítima típica.** A média
inverte a relação porque poucas fraudes de valor alto puxam a distribuição. O padrão é
conhecido na indústria: o fraudador testa o cartão com valores pequenos, que passam
despercebidos, antes de escalar.

Isso tem consequência direta na modelagem: um modelo que aprendesse "fraude é transação
cara" erraria sistematicamente.

![Distribuição de valor](figures/00b_distribuicao_valor.png)
![Comportamento temporal](figures/00c_comportamento_temporal.png)
![Separação por componente](figures/00d_separacao_componentes.png)

---

## 4. Metodologia adotada

### 4.1 Particionamento cronológico

Os dados são ordenados por `Time` e divididos por posição em **70% treino / 15%
validação / 15% teste**, sem embaralhamento. Cada partição é integralmente posterior à
anterior.

| Partição | Linhas | Fraudes | Taxa |
|---|---|---|---|
| Treino | 198.648 | 366 | 0,1842% |
| Validação | 42.721 | 56 | 0,1311% |
| Teste | 42.722 | 52 | 0,1217% |

O `train_test_split` aleatório, padrão na maioria dos trabalhos sobre esta base, permite
que uma transação das primeiras horas caia no teste enquanto transações posteriores estão
no treino. O modelo é avaliado com informação que não teria em operação, e a métrica
resultante não se realiza em produção. É a forma mais comum e mais silenciosa de
vazamento neste dataset.

**A taxa de fraude cai monotonicamente entre as partições** — 0,1842% → 0,1311% →
0,1217%. É evidência direta de não estacionariedade, exatamente o que o split cronológico
deveria expor e o aleatório esconderia. O teste é, portanto, mais difícil que o treino.

### 4.2 Tratamento do desequilíbrio

**Não é usado SMOTE**, nem qualquer reamostragem sintética. Três razões:

As features são componentes de PCA. SMOTE interpola linearmente entre vizinhos no espaço
de atributos; sobre variáveis de PCA, os pontos gerados não correspondem a nenhuma
transação possível. Estaríamos inventando fraudes e afirmando que o modelo aprendeu com
elas.

É a origem mais comum de vazamento nesta base: aplicado antes do split, ou dentro da
validação cruzada sem encapsulamento, cópias sintéticas de positivos de treino aparecem
na avaliação. Boa parte dos resultados espetaculares publicados sobre este dataset vem
daí.

A raridade é a característica definidora do problema, não um artefato de amostragem.
Reequilibrar afasta o modelo da distribuição sobre a qual ele vai operar.

O desequilíbrio é tratado por **ponderação de classe na função de perda**
(`scale_pos_weight`), com a intensidade buscada em vez de fixada.

### 4.3 Engenharia de atributos

Conjunto deliberadamente enxuto — com features anonimizadas há pouco espaço para
derivação semântica, e cada atributo novo é uma chance a mais de vazamento. Todas as
estatísticas são estimadas **exclusivamente no treino**.

| Atributo | Definição | Justificativa |
|---|---|---|
| `Amount_log` | `log1p(Amount)` | assimetria forte (mediana 22, máximo 25.691) |
| `Hour` | `(Time/3600) mod 24` | sazonalidade intradiária sem carregar tendência absoluta |
| `Amount_zscore_by_hour` | desvio do valor frente à média daquela hora | valor atípico *para o horário* informa mais que valor alto absoluto |

`Time` **não** é usado como atributo: é eixo de particionamento. Mantê-lo ensinaria ao
modelo o intervalo específico das 48 horas observadas, que não generaliza.

Duplicatas exatas são removidas **apenas do treino** (716 linhas, 18 delas fraudes). No
teste elas permanecem: se transações idênticas ocorrem na operação real, o conjunto de
avaliação deve refleti-las — limpá-lo seria medir um mundo que não existe.

Total: **32 atributos**.

---

## 5. Pipeline de Machine Learning

```
ingestão → validação da fonte → EDA → split cronológico → engenharia de atributos
   → seleção de candidatos (validação cruzada) → treino + tuning → calibração
   → política de decisão → avaliação → explicabilidade → artefato versionado
   → imagem Docker → serviço com monitoramento
```

O pipeline vive em `src/`, com módulos independentes e um ponto de entrada único
(`run_pipeline.py`). Não há notebook: a solução é entregue como serviço executável.

### 5.1 Seleção de candidatos

Cinco candidatos foram comparados **exclusivamente por validação cruzada temporal** — o
conjunto de teste não participa desta etapa. A métrica é o recall médio na região de
precisão aceitável, que é o requisito operacional real.

| Candidato | Recall @ precisão ≥ 0,80 |
|---|---|
| **XGBoost, espaço ampliado** | **0,8262 ± 0,0420** |
| XGBoost, espaço ampliado + agregados de PCA | 0,8257 ± 0,0425 |
| LightGBM | 0,8257 ± 0,0425 |
| LightGBM + agregados de PCA | 0,8240 ± 0,0400 |
| XGBoost, espaço original | 0,8112 ± 0,0318 |

**Os quatro primeiros estão empatados** — 0,002 de diferença dentro de um desvio de
0,04. O que produziu ganho real foi ampliar o espaço de busca (+0,015 sobre o original);
trocar de algoritmo ou acrescentar atributos derivados das componentes de PCA não mudou
nada. O modelo está num platô, e apresentar a escolha do vencedor como significativa
seria falso.

Uma observação de implementação com valor prático: o **LightGBM só entrou na comparação
depois de ser consertado**. Com 0,18% de positivos, ele inicializa o boosting no logit da
média (≈ −6,3), região em que os gradientes são pequenos demais para as árvores
recuperarem — PR-AUC de 0,2394 com os padrões, contra 0,7929 com `boost_from_average`
desligado. Compará-lo quebrado não seria comparação.

### 5.2 Objetivo do tuning

A busca otimiza **recall na faixa de precisão exigida**, não PR-AUC. PR-AUC resume a
curva inteira, inclusive regiões de precisão baixa que a operação jamais usaria: otimizar
por ela entrega um modelo bom em média e ruim exatamente onde ele opera. Na prática, com
PR-AUC como objetivo a busca escolheu `scale_pos_weight ≈ 518`, ponderação tão agressiva
que destrói a precisão na faixa útil.

A avaliação de cada tentativa é feita por validação cruzada temporal, e não no split
único de validação. Com 56 positivos, 80 tentativas contra um alvo tão pequeno
sobreajustam: uma execução atingiu 0,8811 na validação e caiu para 0,6806 no teste.

### 5.3 Baseline obrigatório

Uma **regressão logística ponderada** é treinada sempre, sob o mesmo protocolo. Não é
formalidade: `V1`–`V28` já são projeções lineares descorrelacionadas, e um modelo linear
opera bem sobre esse tipo de entrada. Se ele empatar com o gradient boosting, isso é
achado, não fracasso.

### 5.4 Calibração

A saída de um gradient boosting não é probabilidade calibrada, e a ponderação de classe
distorce ainda mais a escala. Isso é irrelevante enquanto o modelo apenas ordena — e
passa a ser decisivo quando o escore vira decisão com faixas.

Isotônica e sigmoide são ajustadas **na validação**, e a de menor Brier é escolhida:

| Método | Brier | ECE |
|---|---|---|
| Escore bruto | 0,000510 | 0,011683 |
| **Isotônica** (escolhida) | **0,000284** | **0,000000** |
| Sigmoide (Platt) | 0,000349 | 0,000318 |

![Diagrama de confiabilidade](figures/05_diagrama_confiabilidade.png)

---

## 6. Resultados experimentais

### 6.1 Adoção do modelo

O modelo principal só substitui o baseline se o ganho for estatisticamente distinguível
de ruído, medido por **teste t pareado** sobre as diferenças de PR-AUC por fold:

| | PR-AUC em validação cruzada |
|---|---|
| Regressão logística | 0,7373 ± 0,0881 |
| XGBoost | **0,7978 ± 0,0587** |

`t = 1,988`, `p = 0,0589`, Wilcoxon `p = 0,0625`, vencendo em 4 de 5 folds.

**O p-valor não cruza 0,05.** Pelo critério estatístico isolado, o baseline seria mantido
— e este é um resultado honesto que merece registro: o ganho do gradient boosting sobre
uma regressão logística, nesta base, está no limiar da significância com 5 folds.

O XGBoost foi adotado por um critério independente: **viabilidade operacional**. A
regressão logística não possui nenhum limiar capaz de satisfazer simultaneamente
precisão ≥ 0,80 e recall ≥ 0,75; o XGBoost possui. Um modelo que não consegue operar não
é candidato, por melhor que seja seu PR-AUC.

### 6.2 Desempenho no conjunto de teste

O teste foi tocado **uma única vez**, ao final. Escalonador, calibrador e limiares foram
estimados em treino ou validação.

| Métrica | Obtido | Mínimo exigido | |
|---|---|---|---|
| ROC-AUC | **0,9791** | 0,95 | atingido |
| Recall | **0,7500** | 0,75 | atingido |
| Precisão | **0,7500** | 0,80 | **não atingido** |
| F1 | 0,7500 | — | |
| PR-AUC | 0,7653 | — | |
| Brier | 0,000497 | — | |
| ECE | 0,0000024 | — | |

**Matriz de confusão:**

| | Previsto legítima | Previsto fraude |
|---|---|---|
| **Real legítima** | 42.657 | 13 |
| **Real fraude** | 13 | 39 |

![Curva Precision-Recall](figures/01_curva_precision_recall.png)
![Curva ROC](figures/02_curva_roc.png)
![Matriz de confusão](figures/03_matriz_confusao.png)

### 6.3 Reprodutibilidade

Duas execuções consecutivas do pipeline produzem métricas **idênticas até a décima casa
decimal**, matriz de confusão inclusa.

Chegar a isso exigiu resolver um problema que não era óbvio. O XGBoost com `n_jobs=-1`
soma gradientes em paralelo, e soma de ponto flutuante não é associativa: o resultado
varia nos últimos bits entre execuções. A variação altera o valor do objetivo, que altera
as decisões do amostrador TPE, e o efeito cascateia. Como o objetivo tem um platô, duas
buscas produziram **modelos substancialmente diferentes** — `scale_pos_weight` de 518
contra 15,9 — com desempenho equivalente. A precisão no teste oscilava entre 0,7358 e
0,7500.

A solução separa **busca** de **reprodução**: os hiperparâmetros vencedores são gravados
em arquivo versionado, e execuções seguintes reconstroem o modelo exatamente. É o mesmo
princípio que rege a esteira — o que se promove é o artefato, não o processo que o gerou.

---

## 7. Análise das métricas

### 7.1 Por que PR-AUC e não ROC-AUC

Com 0,17% de positivos, a taxa de falsos positivos tem 284.315 transações legítimas no
denominador: mesmo milhares de falsos positivos mal deslocam o eixo. Valores de ROC-AUC
acima de 0,97 são rotineiros nesta base e não discriminam entre modelos. A curva
Precision-Recall trabalha com duas métricas condicionadas à classe positiva, e responde
ao que muda a operação.

A ROC-AUC de 0,9791 é reportada porque a rubrica a exige — não porque descreva bem o
desempenho.

### 7.2 A precisão não atingida

Este é o resultado que exige análise em vez de justificativa.

**A distância é de 4 transações.** Para atingir 0,80 mantendo os 39 acertos, seriam
necessários no máximo 9 falsos positivos. Há 13.

**A granularidade da medida é grosseira.** Com 52 fraudes no teste, cada fraude vale 1,92
ponto de recall e cada falso positivo eliminado vale ~1,4 ponto de precisão. Não existe
ajuste fino possível nessa escala — a métrica se move em degraus.

**O teste não possui região viável.** Para este modelo, nenhum limiar satisfaz
simultaneamente precisão ≥ 0,80 e recall ≥ 0,75. Quando a precisão ultrapassa 0,80, o
recall trava em 0,7308 — 38 de 52 fraudes. Falta uma transação para os 0,75.

**A causa é metodológica, e deliberada.** Duas decisões deste projeto reduzem as métricas
em troca de validade: o particionamento cronológico, que expõe a não estacionariedade em
vez de escondê-la, e a ausência de reamostragem sintética, que evita inflar o resultado
com fraudes inventadas. Com split aleatório e SMOTE, os mínimos seriam atingidos com
folga — e o número não corresponderia ao desempenho realizável.

Vale registrar o que **não** foi feito: a regra de seleção de limiar não foi reajustada
até o teste passar. Iterar a regra observando o resultado do teste é vazamento por
tentativa e erro, ainda que indireto, e invalidaria toda a avaliação. Uma configuração
anterior marcou 0,7647 no teste, mas era pior em validação cruzada; revertê-la por
resultado de teste seria exatamente esse erro.

### 7.3 Tentativas de melhoria

Antes de congelar o modelo, três caminhos legítimos foram testados, todos comparados
apenas por validação cruzada: ampliar o espaço de busca, trocar por LightGBM, e
acrescentar atributos agregados das componentes de PCA (norma L2, componente mais
extrema, contagem de componentes fora de 3 desvios).

Apenas o espaço ampliado produziu ganho, e modesto. Os demais empataram. O modelo está
num platô.

---

## 8. Política de decisão

A saída do modelo não alimenta um classificador binário, e sim uma política de triagem em
três faixas sobre a probabilidade calibrada:

```
p < t_low            →  aprovar automaticamente
t_low ≤ p < t_high   →  encaminhar para revisão manual
p ≥ t_high           →  bloquear automaticamente
```

Os limiares minimizam o **custo total esperado** sujeito à **capacidade de revisão
manual** — um recurso finito, o que torna o problema interessante.

O modelo de custo assume que a revisão manual **não é perfeita** (taxa de detecção de
90%). A premissa não é cosmética: assumir revisão infalível torna o bloqueio
estritamente dominado — revisar seria sempre mais barato e igualmente eficaz — e a
política de três faixas degenera em duas.

### 8.1 Análise de sensibilidade

Os custos são arbitrados, então a conclusão só é confiável se for robusta a eles. Variando
a razão entre custo de bloqueio indevido e custo de revisão em cinco níveis, e a
capacidade de revisão em cinco:

**As 25 combinações permanecem viáveis**, com custo total entre 359 e 403 — variação de
cerca de 12%. A política não depende de premissas frágeis.

![Sensibilidade](figures/06_sensibilidade_custos.png)

### 8.2 Limitação observada

Medida a distribuição real das faixas no teste, a faixa intermediária mostrou-se
praticamente vazia, e a de bloqueio só captura escores que saturam em exatamente 1,0.

O modelo é confiante a ponto de o comportamento ser quase binário: **51,7% dos escores de
teste são exatamente 0,0**, efeito dos platôs da calibração isotônica. Na prática, a
faixa de revisão manual não capturou fraude alguma no conjunto de teste.

O desenho da política continua correto e a formulação econômica se sustenta — mas, sobre
estes dados e com este modelo, o instrumento tem pouco volume para operar. Um modelo
menos saturado, ou uma calibração menos agressiva, devolveria função à faixa
intermediária.

![Distribuição dos escores](figures/04_distribuicao_escores.png)

---

## 9. Explicabilidade do modelo

A técnica adotada é **SHAP** com `TreeExplainer`, exato para modelos de árvore. A amostra
tem 5.000 transações do teste, estratificada e **contendo todas as 52 fraudes** —
positivos são escassos e são o objeto de interesse.

**Atributos mais influentes:** `V14`, `V10`, `V12`, `V4`, `V17`, `V11`, `V16`, `V19`.

![Importância SHAP](figures/08_importancia_shap.png)

### 9.1 Uma limitação que precisa ser dita

Todos os oito atributos mais influentes são **componentes de PCA anonimizadas**. Nenhuma
técnica de explicabilidade pode dizer o que `V14` significa em termos de negócio: essa
informação foi destruída na anonimização do dataset original. Atribuir sentido semântico
a essas variáveis seria fabricação.

O que **é** possível afirmar com base na evidência: o modelo apoia sua decisão
predominantemente na estrutura latente capturada pelo PCA, e não em `Amount` ou `Hour`,
que são os únicos atributos diretamente interpretáveis. Isso é coerente com o achado da
exploração — fraude não se distingue pelo valor.

A explicação local é gerada para três casos escolhidos deterministicamente: um verdadeiro
positivo de alta confiança, um falso positivo e um falso negativo. Os dois últimos são os
mais informativos e os que costumam ser omitidos.

Em operação, a mesma explicação acompanha cada transação encaminhada à revisão manual,
para que o analista veja quais fatores empurraram o escore.

---

## 10. Estratégia de monitoramento

### 10.1 O problema que define a estratégia

Propostas de monitoramento costumam assumir que se acompanha a acurácia em produção. **Em
detecção de fraude isso é falso**, e essa é a característica central do problema
operacional.

O rótulo verdadeiro chega por chargeback, com prazos regulatórios de até 120 dias.
Decorre daí:

- **Recall não é observável em tempo real.** Fraudes não detectadas hoje só se revelam em
  semanas. Um painel de recall diário mede sempre um passado incompleto.
- **Os rótulos disponíveis são enviesados por seleção.** Transações bloqueadas nunca
  geram chargeback — o modelo interfere na coleta do rótulo que serviria para avaliá-lo.

### 10.2 Três camadas, ordenadas por latência

| Camada | Sinal | Latência |
|---|---|---|
| 1 | PSI e KS por atributo; distribuição dos escores; frações por faixa | imediata |
| 2 | Precisão na faixa de revisão manual; uso da capacidade | horas |
| 3 | Recall e custo confirmados por chargeback | semanas |

A camada 2 é a contribuição da política de três faixas para a observabilidade: a fila de
revisão é o único ponto do sistema que produz rótulo humano em horas. Está implementada e
exposta em `/monitoring/review-precision`.

### 10.3 Drift medido

Comparando treino e teste — períodos distintos por construção — **15 dos 32 atributos**
estão fora da faixa estável.

| Atributo | PSI | Severidade |
|---|---|---|
| `Hour` | 10,0748 | drift |
| `V1` | 1,0129 | drift |
| `V3` | 0,7510 | drift |
| `V28` | 0,5335 | drift |

O PSI de `Hour` **não indica degradação do modelo**: é artefato do desenho experimental.
O treino cobre 37 horas e o teste apenas 6, então as horas do dia não coincidem por
construção. É consequência de a base ter apenas 48 horas, e é um argumento contra manter
`Hour` como atributo em um sistema real — ele não generaliza para períodos não
observados.

Os demais indicam não estacionariedade genuína, coerente com a queda da taxa de fraude
entre as partições.

![Drift](figures/07_drift_psi.png)

### 10.4 Gatilhos de retreino

Dispara o que ocorrer primeiro: PSI acima de 0,25 em atributo entre os 10 mais
importantes por SHAP; queda da precisão na faixa de revisão além da tolerância; ou
agenda periódica, como piso de segurança.

### 10.5 Operacionalização

O sistema roda como serviço, com estado persistido em PostgreSQL:

- decisões gravadas com **os limiares vigentes no momento** — sem isso a decisão deixa de
  ser auditável assim que a política mudar;
- fila de revisão manual consultável, com registro do veredito do analista;
- versão do modelo em produção registrada, com `git_sha`, hash dos dados e métricas.

A persistência é opcional: sem `DATABASE_URL` a API responde inferência normalmente e não
grava, preservando o caminho de avaliação com um único comando.

A esteira segue `develop → homolog → main`, com **promoção de artefato**: produção não
retreina, promove por retag o mesmo digest de imagem validado em homologação. A versão é
calculada automaticamente a partir dos Conventional Commits.

---

## 11. Conclusão

A solução entrega um pipeline completo de detecção de fraude, do dado público ao serviço
em execução, com **ROC-AUC de 0,9791** e **recall de 0,7500** no conjunto de teste,
probabilidades calibradas (ECE de 0,0000024) e reprodutibilidade verificada até a décima
casa decimal.

A **precisão de 0,7500 não atinge o mínimo de 0,80**. A distância é de quatro transações
entre 42.722, e a análise mostra que o conjunto de teste não possui região viável para
este modelo. A causa está em duas decisões metodológicas deliberadas — particionamento
cronológico e ausência de reamostragem sintética — que reduzem as métricas em troca de
validade. Com split aleatório e SMOTE os mínimos seriam atingidos com folga, e os números
não corresponderiam ao desempenho realizável em produção.

### Achados honestos

Além do já exposto, três resultados merecem registro por contrariarem a expectativa:

**O ganho do gradient boosting sobre a regressão logística está no limiar da
significância** (`p = 0,0589`). As componentes de PCA já são projeções lineares
descorrelacionadas, e um modelo linear opera bem sobre elas. A adoção do XGBoost se
sustentou em viabilidade operacional, não em superioridade estatística demonstrada.

**A faixa de revisão manual, que é o diferencial da formulação, não capturou fraude
alguma no teste.** O modelo é confiante demais para que a faixa intermediária tenha
volume.

**Configurações de hiperparâmetros muito distintas alcançam desempenho equivalente.** O
objetivo tem um platô, e a escolha entre elas é arbitrária dentro do ruído — o que
motivou travar os parâmetros para garantir reprodutibilidade.

### Trabalhos futuros

Reajustar o modelo final em treino + validação, aproveitando 422 fraudes em vez de 366,
migrando a calibração para predições fora-de-fold. Substituir `Hour` por um atributo
temporal que generalize. Avaliar com uma janela de teste maior, que reduza a granularidade
grosseira imposta por 52 positivos. E validar a política de três faixas sobre um modelo
menos saturado, onde a faixa intermediária tenha volume operacional.

---

**Reprodução:**

```bash
git clone https://github.com/diegoedataengineer/fraud-triage
cd fraud-triage && docker compose up          # ecossistema completo
docker run -p 8000:8000 diegodataengineer/fraud-triage:0.1.0   # só o serviço
```
