# O que foi feito e como foi feito

Atualizado em 11/11/2026. Este documento resume o artefato presente nesta cópia do projeto e distingue a implementação dos resultados observados na demonstração.

## Objetivo e recorte

Foi construído um protótipo acadêmico para apoiar a investigação de falhas em uma aplicação distribuída. O cenário usa uma loja virtual fictícia: uma consulta entra pelo **Gateway**, passa por **Orders** e depende de **Users**. A indisponibilidade de Users permite observar como uma falha em uma dependência aparece nos demais serviços. O operador informa uma janela de tempo, um serviço e, opcionalmente, o ID da requisição para obter um diagnóstico fundamentado em evidências.

## Componentes implementados

| Entrega | Como foi feita | Onde consultar |
| --- | --- | --- |
| Aplicação distribuída | Três APIs FastAPI simulam Gateway, Orders e Users. O cliente HTTP propaga `X-Request-ID`; middleware e logs estruturados registram a passagem da requisição e falhas nas dependências. | `app/microservices/`, `app/telemetry.py`, `app/models.py` |
| Coleta de observabilidade | Um coletor consulta `/health` e `/metrics`, obtém métricas de processo e sistema com psutil e ingere os logs JSONL dos serviços. | `app/monitoring/collector.py`, `metrics.py`, `ingestion.py` |
| Estado atual e histórico | O snapshot atual é publicado no etcd com prazo de validade. Snapshots, logs, checkpoints de ingestão e execuções de diagnóstico são persistidos no PostgreSQL por SQLAlchemy; o esquema é versionado com Alembic. | `app/monitoring/current.py`, `storage.py`, `app/migrations/` |
| Seleção do contexto | Consultas filtram a janela temporal, o serviço e suas dependências e o request ID. O contexto reúne evidências identificadas, aplica limites de tamanho e informa truncamento ou itens omitidos. | `app/monitoring/context.py`, `models.py` |
| Diagnóstico com LLM | Uma cadeia LangChain compõe prompt, contexto e modelo de chat usando uma API compatível com Chat Completions. A resposta é validada por schema e cada `evidence_id` precisa pertencer ao contexto enviado. Uma saída inválida admite uma tentativa de correção; tentativas e respostas brutas são preservadas. | `app/monitoring/providers.py`, `diagnostics.py` |
| Interface de investigação | A CLI permite consultar estado atual, contexto, evidência, execução e histórico, além de solicitar um diagnóstico. Uma interface web executa os cenários e mostra o diagnóstico ao lado do gabarito. | `app/cli.py`, `presentation/` |
| Gatilho automático | O coletor publica no etcd sinais de negócio por serviço (taxa de erro, p95, falhas de dependência). O serviço `trigger` observa essa chave e, quando um limite guardado no etcd é violado, pede o diagnóstico sozinho, uma vez por incidente. | `app/monitoring/signals.py`, `trigger.py`, [gatilho-automatico.md](gatilho-automatico.md) |
| Cenários e avaliação | Oito cenários injetam falhas conhecidas (Users parado, sobrecarga, erro interno e falha intermitente no Orders, lentidão, instrução maliciosa em log, dois controles). A avaliação em lote compara a IA com health checks e com uma sonda sintética. | `experiments/scenarios.py`, `evaluate.py`, [avaliacao.md](avaliacao.md) |
| Ambiente reproduzível | Docker Compose reúne as APIs, o coletor, etcd, PostgreSQL e o comando de diagnóstico. As migrações são executadas antes do coletor. | `docker-compose.yaml`, `Dockerfile`, `.env.example` |
| Experimento | Um script executa as fases normal, indisponibilidade de Users e recuperação, coleta os registros de cada fase e tenta restaurar os serviços ao final. O controle da falha fica separado das evidências fornecidas à LLM. | `experiments/demonstrate.py`, `docs/evidencias/` |

## Como o fluxo funciona

1. Uma chamada a `GET /orders/1` atravessa Gateway, Orders e Users com o mesmo request ID.
2. Cada serviço produz logs estruturados; o coletor registra saúde, métricas e eventos no histórico.
3. O snapshot mais recente é publicado no etcd. O histórico permanece no PostgreSQL para consultas posteriores.
4. A CLI monta um contexto limitado com os registros pertinentes à investigação.
5. A LLM recebe esse contexto e devolve uma resposta estruturada. O sistema valida o formato e as referências às evidências antes de registrar o resultado.
6. O operador pode recuperar a execução e abrir as evidências originais pelos IDs citados.

No modo automático, os passos 4 e 5 são iniciados pelo gatilho: a cada snapshot, os
sinais são comparados com os limites e, na primeira violação de um incidente, o
diagnóstico da janela recente é solicitado sem intervenção do operador.

## O que foi observado

### Avaliação com gabarito (11/11/2026)

Uma rodada dos oito cenários, mais um controle repetido, com gpt-5
([relatório](evidencias/avaliacao-20261112T013517Z-fd1887/relatorio.md)):

| Método | Detecção correta | Localização correta (incidentes) | Falsos positivos (controles) |
| --- | --- | --- | --- |
| Health checks | 5/9 | 2/6 | 0/3 |
| Sonda sintética | 9/9 | 0/6 | 0/3 |
| IA (artefato) | 9/9 | 6/6 | 0/3 |

Health checks só perceberam os incidentes em que um processo parou; a sonda
detectou todos, mas sempre na entrada. A IA localizou a origem nos seis
incidentes, não alarmou nos controles e manteve o diagnóstico quando um log
continha instruções para negá-lo. Com uma execução por cenário, o resultado
indica tendência, não taxa de acerto.

O gatilho automático disparou nos seis incidentes e em nenhum controle, entre
2 e 6 s após o início da falha. Os limites sozinhos não localizam a origem:
na sobrecarga e na lentidão os três serviços violam ao mesmo tempo.

### Demonstração de 24/09/2026

O registro mais recente disponível está em [`docs/evidencias/20260924T221853Z-40eb62/`](evidencias/20260924T221853Z-40eb62/relatorio.md). O arquivo `resumo.json` informa que o pipeline passou, Users foi restaurado, uma LLM real foi utilizada e os resultados esperados foram observados:

| Fase | HTTP | Resultado do diagnóstico |
| --- | ---: | --- |
| Consulta normal | 200 | `no_incident` |
| Users indisponível | 504 | `incident` |
| Após recuperação | 200 | `no_incident` |

Os JSONs de cada fase preservam requisição, contexto, evidências e execução. `controle-experimental.json` registra as intervenções externas e não é ingerido pelo sistema. Esse ensaio demonstra o funcionamento do cenário e da cadeia de diagnóstico; ele não mede a acurácia da solução em outros incidentes.

O documento [`entrega.md`](entrega.md) descreve uma execução histórica anterior com LLM simulada. Ela não representa o estado do ensaio mais recente. Também registra 61 testes aprovados naquela etapa; essa contagem não foi repetida. A suíte atual em `tests/` tem 24 testes, todos aprovados.

## Limites atuais

- Os dados de pedidos e usuários são fictícios e mantidos em memória.
- O ambiente usa um único coletor e um único membro etcd; não oferece autenticação de produção, alta disponibilidade nem retenção e rotação automática de logs.
- A validade do schema e das referências garante rastreabilidade, mas não comprova que a hipótese da LLM esteja semanticamente correta.
- A avaliação registrada tem uma execução por cenário; mais repetições, falhas definidas por terceiros e critérios de qualidade textual, latência e custo ampliariam a validade.
- Os limites do gatilho são fixos e definidos manualmente.

Para reproduzir a demonstração, siga [`demonstracao.md`](demonstracao.md). Para os detalhes do caso de uso, consulte [`caso-de-uso.md`](caso-de-uso.md).
