# Entrega — versão funcional e demonstração

## Artefato

Protótipo executável de apoio ao diagnóstico de falhas em sistemas distribuídos,
com três APIs, coleta de métricas e logs, estado atual no etcd, histórico no
PostgreSQL e interface de investigação por linha de comando.

O diagnóstico recebe um contexto delimitado e cita IDs de evidências.
Solicitação, contexto, respostas brutas, tentativas e resultado ficam persistidos.
A integração com LLM utiliza LangChain (prompt → modelo de chat → texto validado); a execução com o provedor real do
estudante permanece pendente de modelo, endereço da API e configuração da chave.

## Cenário de aplicação

Consulta de um pedido em uma loja virtual simulada. Gateway consulta Orders,
que depende de Users. A interrupção de Users prejudica a consulta do pedido e
produz evidências de falha distribuídas entre os serviços.

Detalhamento: [cenário e caso de uso UC-01](caso-de-uso.md).

## Caso de uso

O operador informa a janela de tempo, o serviço e o request ID da consulta com
falha. O artefato reúne evidências, solicita análise à LLM, valida a resposta e
permite consultar os registros citados. A intervenção no ambiente continua a
cargo do operador.

## Demonstração executada

Execução registrada em **24/09/2026, 15:03 UTC (12:03 em São Paulo)**.

| Momento | HTTP observado | Evidências verificadas |
| --- | --- | --- |
| Consulta normal | 200 | 6 |
| Users indisponível | 504 | 5 |
| Consulta após recuperação | 200 | 6 |

Foram verificadas a correlação dos logs, a correspondência do snapshot no etcd,
a recuperação das evidências originais no PostgreSQL e a persistência das
execuções. Users e o coletor foram restaurados; os seis componentes permaneceram
saudáveis após o cenário.

**A LLM foi simulada nesta execução.** O stub devolveu `insufficient_evidence`
nas três etapas e não produziu hipóteses. O resultado comprova funcionamento
do fluxo de dados e rastreabilidade; a demonstração de diagnóstico por IA com o
provedor real continua pendente.

- [Relatório observado](evidencias/20260924T150304Z-b3a6b6/relatorio.md).
- [Resumo estruturado](evidencias/20260924T150304Z-b3a6b6/resumo.json).
- [Evidências da indisponibilidade](evidencias/20260924T150304Z-b3a6b6/indisponibilidade.json).
- [Roteiro para repetir a apresentação](demonstracao.md).

O ensaio anterior também foi preservado: nele, o roteiro esperava somente 503
e observou 504. O critério foi ajustado para os dois modos de falha previstos
na aplicação, exigindo logs que apontem a dependência Users.

## Verificação da implementação

- 61 testes automatizados aprovados após a integração com LangChain.
- Ruff: lint e formatação aprovados.
- mypy: sem erros em 43 arquivos Python.
- Compose: configuração válida, migração aplicada e serviços saudáveis.
- Verificação HTTP adicional: Gateway → Orders → Users com request ID comum.

## Conclusão da etapa e pendência

A infraestrutura do artefato e a reprodução da instância do problema estão
funcionais. Para concluir a demonstração com IA, configurar o provedor real e
executar:

```powershell
.\.venv\Scripts\python.exe -B scripts\demonstrate.py --require-real
```

Esse modo exige uma LLM real e verifica os resultados esperados das três etapas,
incluindo uma hipótese referente a Users na indisponibilidade. As evidências
devem ser examinadas pelo estudante antes de interpretar o resultado.

Esta entrega demonstra viabilidade técnica no cenário simulado. A avaliação
formal de acurácia, utilidade e desempenho será uma etapa posterior.