# Entrega — versão funcional e demonstração

## Artefato

Protótipo executável de apoio ao diagnóstico de falhas em sistemas distribuídos,
com três APIs, coleta de métricas e logs, estado atual no etcd, histórico no
PostgreSQL e interface de investigação por linha de comando.

O diagnóstico recebe um contexto delimitado e cita IDs de evidências.
Solicitação, contexto, respostas brutas, tentativas e resultado ficam persistidos.
A integração com LLM utiliza LangChain (prompt → modelo de chat → texto validado).
Há uma execução registrada com LLM real em 24/09/2026. Para repetir o cenário,
é necessário configurar modelo, endereço da API e chave localmente.

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

Execução com LLM real registrada em **24/09/2026, 22:21 UTC (19:21 em São Paulo)**.

| Momento | HTTP observado | Resultado do diagnóstico |
| --- | --- | --- |
| Consulta normal | 200 | `no_incident` |
| Users indisponível | 504 | `incident`, com hipótese referente a Users |
| Consulta após recuperação | 200 | `no_incident` |

Foram verificadas a correlação dos logs, a correspondência do snapshot no etcd,
a recuperação das evidências originais no PostgreSQL e a persistência das
execuções. Users e o coletor foram restaurados; os seis componentes permaneceram
saudáveis após o cenário.

O resumo da execução registra `real_llm_used: true`,
`diagnostic_demonstration_passed: true` e `users_restored: true`.
Durante a indisponibilidade, o diagnóstico indicou timeouts ao acessar Users e
a propagação da falha por Orders até o Gateway, com referências a evidências.
O ensaio anterior com LLM simulada comprovava somente o fluxo de dados; ele
não deve ser confundido com esta execução posterior com diagnóstico real.

- [Relatório observado](evidencias/20260924T221853Z-40eb62/relatorio.md).
- [Resumo estruturado](evidencias/20260924T221853Z-40eb62/resumo.json).
- [Evidências da indisponibilidade](evidencias/20260924T221853Z-40eb62/indisponibilidade.json).
- [Roteiro para repetir a apresentação](demonstracao.md).
- [Caso de uso elaborado para apresentação](caso-de-uso-apresentacao.md).

O roteiro aceita 503 e 504, os dois modos de falha previstos na aplicação,
exigindo logs que apontem a dependência Users.

## Verificação da implementação na execução registrada

- 61 testes automatizados aprovados após a integração com LangChain.
- Ruff: lint e formatação aprovados.
- mypy: sem erros em 43 arquivos Python.
- Compose: configuração válida, migração aplicada e serviços saudáveis.
- Verificação HTTP adicional: Gateway → Orders → Users com request ID comum.

## Conclusão da etapa e pendência

A infraestrutura e o diagnóstico com IA possuem evidências de execução no
cenário simulado. Para repetir a demonstração de forma guiada, configurar o
provedor real e executar:

```powershell
.\.venv\Scripts\python.exe -B experiments\demonstrate.py --interactive --samples 3
```

Esse modo exige uma LLM real e verifica os resultados esperados das três etapas,
incluindo uma hipótese referente a Users na indisponibilidade. As evidências
devem ser examinadas pelo estudante antes de interpretar o resultado.

O roteiro atualizado registra também amostras de consultas, latências no cliente
e health do Gateway. Essas medições adicionais ainda precisam ser obtidas numa
nova execução; não fazem parte do registro histórico citado acima.

Esta entrega demonstra viabilidade técnica no cenário simulado. A avaliação
formal de acurácia, utilidade e desempenho será uma etapa posterior.
