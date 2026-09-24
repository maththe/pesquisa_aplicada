# Cenário de aplicação e caso de uso

## Problema investigado

Em uma aplicação distribuída, uma falha percebida no serviço de entrada pode ter
origem em uma dependência. Logs separados e métricas sem contexto dificultam
reconstituir a sequência de chamadas. O artefato reúne evidências correlacionadas
e fornece esse contexto a uma LLM para apoiar a investigação humana.

Este recorte foi extraído da arquitetura e do plano existentes no projeto.
Não representa um estudo empírico de uma organização específica.

## Cenário representativo

Uma loja virtual simulada permite consultar um pedido. O Gateway recebe a
requisição, Orders busca os dados do pedido e consulta Users para incluir o
usuário. O pedido e o usuário de ID 1 são dados fictícios em memória.

No cenário de indisponibilidade, o processo Users é interrompido externamente.
A consulta ao pedido retorna HTTP 503 ou 504, embora Gateway e Orders possam responder
normalmente a seus próprios healthchecks. Esse contraste permite investigar
propagação de falhas entre dependências.

O controlador experimental conhece a intervenção realizada. A LLM recebe
somente logs e snapshots da janela selecionada; não recebe os rótulos da
intervenção nem o arquivo que registra a parada do container.

## UC-01 — Investigar falha na consulta de pedido

| Item | Especificação |
| --- | --- |
| Ator principal | Operador responsável pela aplicação |
| Objetivo | Investigar a falha e consultar as evidências que sustentam as hipóteses |
| Gatilho | Consulta de pedido retorna erro |
| Entrada | Janela temporal, serviço de interesse e X-Request-ID |
| Pré-condições | Serviços iniciados, coleta ativa, histórico disponível; provedor real configurado para inferência |
| Saída | Diagnóstico estruturado, limitações, sugestões e IDs de evidências |
| Pós-condição | Execução persistida e recuperável pelo ID; decisões de intervenção permanecem humanas |

Fluxo principal:

1. O operador reproduz a consulta `GET /orders/1` com um request ID.
2. Os serviços propagam o ID e registram eventos estruturados.
3. O coletor sonda saúde e métricas, ingere logs e preserva o histórico.
4. O operador solicita diagnóstico para a janela da ocorrência.
5. O Context Builder seleciona evidências por tempo, serviço/dependências e request ID.
6. A LLM recebe o contexto delimitado e devolve uma hipótese com referências.
7. O sistema valida o schema e verifica se cada referência existe no contexto.
8. O operador consulta as evidências originais e considera as sugestões.
9. O controlador restaura Users e verifica uma nova consulta bem-sucedida.

Fluxos alternativos:

- Sem evidências suficientes, a resposta pode ser `insufficient_evidence`.
- Sem incidente observado, a resposta pode ser `no_incident`, com evidências.
- Saída inválida admite uma tentativa de correção; persistindo o problema,
  a execução termina como `failure`, preservando ambas as respostas.
- Falha de transporte da LLM termina como `failure`, sem diagnóstico por regras.
- Indisponibilidade do etcd não apaga o snapshot gravado no histórico.
- Linhas JSONL incompletas aguardam conclusão; linhas inválidas completas geram
  rejeição registrada, e não evidência de diagnóstico.

## Resultados esperados para a demonstração

| Etapa | Comportamento técnico esperado | Interpretação esperada de uma LLM real |
| --- | --- | --- |
| Normal | HTTP 200, logs nos três serviços e snapshot acessível | Nenhum incidente na requisição observada |
| Users indisponível | HTTP 503 ou 504, falha Orders → Users e propagação ao Gateway | Hipótese de indisponibilidade de Users apoiada nos IDs |
| Recuperação | HTTP 200 e Users novamente acessível | Nenhum incidente na nova requisição observada |

A conclusão da segunda etapa deve distinguir a indisponibilidade observada
da causa da indisponibilidade. Os dados não autorizam afirmar que o operador
executou uma parada Docker, porque esse registro não é fornecido ao modelo.

## Critérios de viabilidade

- A mesma requisição é rastreável entre os serviços envolvidos.
- A falha é reproduzível e produz evidências acessíveis no histórico.
- O snapshot do etcd corresponde à coleta e possui validade limitada.
- O contexto respeita os limites e informa truncamento e ausência de dados.
- Toda referência citada resolve para uma evidência realmente enviada ao modelo.
- Solicitação, contexto, tentativas e resultado podem ser consultados posteriormente.
- O cenário encerra com Users restaurado e a consulta funcionando.

Com provedor real, registrar adicionalmente se os resultados observados
correspondem às três situações e se as hipóteses são sustentadas semanticamente.
A comparação automática de resultados é uma verificação do cenário; a análise
humana permanece necessária.

## Relação com a DSRM

Esta entrega corresponde à construção e à demonstração de viabilidade do
artefato em uma instância simulada do problema. Os registros mostram execução
das funções previstas e permitem inspecionar os resultados.

Não são apresentadas alegações de acurácia, redução de tempo de diagnóstico ou
superioridade frente a métodos existentes. Uma avaliação formal deverá definir
múltiplos cenários, repetições, critérios de correção, comparação com uma referência
e medidas como precisão das hipóteses, cobertura das evidências, latência e custo.