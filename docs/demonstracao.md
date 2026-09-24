# Roteiro de demonstração prática

Duração sugerida: 8 a 12 minutos, além da construção inicial das imagens.
Abra o terminal na raiz do projeto e deixe a pasta de evidências disponível.

## Preparação

1. Execute `docker compose up --build -d --wait`.
2. Confirme os componentes com `docker compose ps`.
3. Configure a API real no arquivo `.env`, conforme o README.
4. Instale as dependências locais com
   `.\.venv\Scripts\python.exe -m pip install -e ".[dev]"`.

Não é necessário expor a chave da API durante a apresentação.

## Apresentação

| Tempo | Ação | Explicação |
| --- | --- | --- |
| 0–1 min | Apresentar o problema | Erro no Gateway pode ser consequência de uma dependência |
| 1–2 min | Mostrar a arquitetura e a consulta de pedido | Gateway → Orders → Users; dados fictícios de ID 1 |
| 2–5 min | Executar o cenário automatizado | Consulta normal, indisponibilidade e recuperação |
| 5–8 min | Abrir os JSONs gerados | Correlacionar logs, snapshot, contexto e diagnóstico |
| 8–10 min | Consultar uma evidência e uma execução | Demonstrar rastreabilidade e persistência |
| 10–12 min | Discutir limites | Demonstração de viabilidade e próximos passos da avaliação |

Execute o cenário com a LLM real:

```powershell
.\.venv\Scripts\python.exe -B experiments\demonstrate.py
```

O script pausa o coletor periódico, faz coletas delimitadas por etapa e reinicia
o coletor ao final. Interrompe somente Users para produzir a indisponibilidade;
o bloco de finalização tenta restaurá-lo inclusive quando uma verificação falha.
A restauração e eventuais erros aparecem no relatório.

Configure `OBS_LLM_URL`, `OBS_LLM_MODEL` e `OBS_LLM_API_KEY` antes da demonstração.
Para verificar apenas a infraestrutura, use os comandos `collect --once`, `current`
e `context` da CLI, que não exigem credenciais de LLM.

## Arquivos produzidos

Cada execução cria uma pasta `docs/evidencias/<data>-<id>/`.

| Arquivo | Conteúdo |
| --- | --- |
| `normal.json` | HTTP, request ID, coleta, snapshot e execução da etapa normal |
| `indisponibilidade.json` | Mesmos dados durante a falha |
| `recuperacao.json` | Mesmos dados após o restabelecimento |
| `resumo.json` | Resultado das verificações e identificação do modo da LLM |
| `relatorio.md` | Registro resumido para apresentação |
| `controle-experimental.json` | Ações externas e horários, sem ingestão pelo artefato |

Durante a apresentação, abra `indisponibilidade.json` e localize:

1. `http_status: 503` ou `504` e o request ID.
2. Evento `dependency_unavailable` ou `dependency_timeout` de Orders apontando para Users.
3. Erro propagado ao Gateway.
4. Snapshot indicando Users inacessível.
5. `run.context`, que contém exatamente as evidências selecionadas.
6. `run.response` e seus `evidence_ids`.
7. `run.executions`, que contém respostas brutas e erros de validação, se ocorreram.

Use IDs reais copiados do relatório:

```powershell
docker compose run --rm --no-deps diagnostics evidence ID_DA_EVIDENCIA
docker compose run --rm --no-deps diagnostics run ID_DA_EXECUCAO
docker compose run --rm --no-deps diagnostics history
```

A última consulta de pedido deve retornar HTTP 200, e `docker compose ps`
deve mostrar Users e o coletor novamente ativos.

## O que relatar na entrega

Descreva o comportamento efetivamente observado, anexando os JSONs e o relatório.
Se o provedor real falhar, preserve o resultado e a mensagem de
validação; não substitua o resultado observado por uma resposta esperada.

O diagnóstico pode reconhecer a falha de conexão com Users sem determinar por
que o processo ficou indisponível. Essa incerteza é coerente com o conjunto de
evidências fornecido.

## Recuperação manual, se a execução for encerrada à força

```powershell
docker compose start users-service
docker compose start collector
docker compose ps
Invoke-RestMethod http://localhost:8000/orders/1
```

## Fontes técnicas da implementação

- [SQLAlchemy: conexões e transações](https://docs.sqlalchemy.org/en/20/core/connections.html).
- [Alembic: migrações versionadas](https://alembic.sqlalchemy.org/en/latest/tutorial.html).
- [etcd3gw: cliente, leases e operações de chave](https://docs.openstack.org/etcd3gw/latest/_modules/etcd3gw/client.html).
- [psutil: métricas de processos e do sistema](https://psutil.readthedocs.io/stable/).
