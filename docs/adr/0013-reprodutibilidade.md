# ADR-0013 — Centralizar configuração, fixar sementes e travar versões

**Status:** Aceita
**Data:** 2026-08-20
**Alterada por:** [ADR-0023](0023-hiperparametros-travados.md) (quarta fonte de variação)

## Contexto

O critério é explícito: o notebook será reexecutado e "diferenças significativas nas
métricas, gráficos, tabelas ou previsões poderão resultar em desconto na nota".
Reprodutibilidade deixa de ser boa prática e passa a ser requisito de nota.

São três fontes distintas de variação, e cada uma exige tratamento próprio:

1. **Aleatoriedade** — particionamento, inicialização do modelo, amostragem do Optuna,
   amostragem do SHAP. Sem semente fixa, cada execução dá um resultado.
2. **Versões de biblioteca** — resolução por faixa (`>=`) instala versões diferentes em
   momentos diferentes. `shap` e `numpy` têm histórico documentado de incompatibilidade
   que quebra a execução, não apenas altera números.
3. **Ambiente** — caminhos locais e variáveis de ambiente que existem na máquina de quem
   desenvolveu e não na de quem corrige.

## Decisão

Três medidas, uma para cada fonte:

**Configuração central.** Todo caminho, hiperparâmetro, limiar, semente e parâmetro de
custo vive em `config/config.yaml`, lido por `src/utils.py`. Nenhum valor mágico
espalhado pelos módulos. Trocar orçamento de tuning ou premissa de custo não exige tocar
em código Python.

**Semente única e propagada.** Uma semente declarada em configuração, aplicada a `random`,
`numpy`, ao modelo, ao amostrador do Optuna e à amostragem do SHAP. Toda função que
sorteia recebe a semente explicitamente — nunca depende do estado global.

**Versões travadas.** `requirements.txt` fixa versões exatas (`==`), nunca faixas. O
custo é atualização manual; o benefício é que "reproduz aqui" e "reproduz na correção"
significam a mesma coisa.

Complementarmente: nenhum caminho absoluto no código — todos derivam da raiz do
repositório; e os artefatos de execução (métricas, limiares, versões efetivamente
instaladas) são gravados em JSON em `reports/`, permitindo comparar duas execuções
objetivamente em vez de por impressão.

## Alternativas consideradas

- **Faixas de versão (`>=`).** Recebem correções de segurança automaticamente. Descartada
  porque a reexecução na correção acontece em data futura e desconhecida: qualquer
  atualização incompatível nesse intervalo quebra a entrega, e não teríamos como saber.
- **Semente por módulo.** Daria controle fino. Descartada por multiplicar pontos de falha,
  sem benefício real neste escopo.
- **Conteinerização com Docker.** Reprodutibilidade mais forte que qualquer uma das
  medidas acima. Descartada porque o Colab não executa contêineres, e o Colab é o
  ambiente de correção.
- **Fixar também a versão do Python.** Desejável, mas o Colab define a versão e não a
  controlamos. Mitigado declarando a versão testada no README e evitando recursos
  recentes de linguagem.

## Consequências

- Atualizações de dependência passam a ser manuais e deliberadas — aceito.
- A configuração central torna trivial rodar em modo reduzido (menos tentativas de
  Optuna) em ambiente limitado, sem divergir do código de produção.
- Os artefatos JSON em `reports/` permitem que a comparação entre a execução relatada e a
  da correção seja factual.
- Não há garantia absoluta: o Colab pode alterar a imagem base. Reduzimos a superfície,
  não a eliminamos — e o README declara a versão testada.
