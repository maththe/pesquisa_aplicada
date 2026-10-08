# Diagnóstico de falhas em sistemas distribuídos

Protótipo acadêmico para apoiar um operador na investigação de falhas no fluxo
**Gateway → Orders → Users**. A versão funcional coleta métricas e logs, mantém
estado atual no etcd e histórico no PostgreSQL, constrói um contexto delimitado
e registra diagnósticos com evidências rastreáveis.

A interface desta versão é uma CLI. O diagnóstico usa LangChain com uma API no
formato Chat Completions e exige modelo, URL e chave. Coleta e consultas ao
histórico funcionam independentemente dessas credenciais.

## Entregas acadêmicas

- [O que foi feito e como foi feito](docs/o-que-foi-feito.md).
- [Entrega consolidada e resultados observados](docs/entrega.md).

- [Cenário, caso de uso e critérios de demonstração](docs/caso-de-uso.md).
- [Roteiro de apresentação e execução](docs/demonstracao.md).
- [Estado da implementação e limitações](docs/estado-da-implementacao.md).
- `docs/evidencias/`: registros gerados a cada execução, sem sobrescrever anteriores.

## Executar

Com Docker Engine e Compose disponíveis, configure o `.env` conforme a seção
seguinte antes de executar o diagnóstico:

```powershell
docker compose up --build -d --wait
Invoke-RestMethod http://localhost:8000/orders/1 -Headers @{ 'X-Request-ID' = 'req-demo-123' }
docker compose run --rm --no-deps diagnostics current
docker compose run --rm --no-deps diagnostics diagnose --service gateway --request-id req-demo-123
docker compose run --rm --no-deps diagnostics history
```

O diagnóstico usa os últimos cinco minutos por padrão. Aguarde um ciclo de coleta
(aproximadamente cinco segundos) depois da requisição. Datas fornecidas em
`--start` e `--end` devem conter timezone. O intervalo máximo é de 24 horas.

| Componente | Endereço local | Função |
| --- | --- | --- |
| Gateway | http://localhost:8000/docs | Entrada, consulta de pedidos e usuários |
| Users | http://localhost:8001/docs | Usuário de demonstração, ID 1 |
| Orders | http://localhost:8002/docs | Pedido de demonstração, ID 1 |
| etcd | http://localhost:2379 | Snapshot atual com validade limitada |
| PostgreSQL | Rede interna do Compose | Histórico, checkpoints e execuções |
| Collector | Processo em segundo plano | Sondagens e ingestão periódica |

As três APIs oferecem `/health` e `/metrics`. IDs de negócio diferentes de 1
retornam 404. Health verifica o processo local. Timeout de dependência retorna
504; falha de conexão, 503; resposta incompatível com o schema, 502.
As portas publicadas estão vinculadas a 127.0.0.1. Para encerrar preservando os
dados, execute `docker compose down`.

## Configurar a LLM real

Copie `.env.example` para `.env` e configure localmente:

```dotenv
OBS_LLM_URL=https://seu-provedor/endereco-completo/chat/completions
OBS_LLM_MODEL=seu-modelo
OBS_LLM_API_KEY=sua-chave-local
```

O endereço acima é um marcador: use o endpoint real do seu provedor.
Também é aceita a URL base, como `https://seu-provedor/v1`; nesse caso,
o cliente acrescenta `/chat/completions`. A chave é obrigatória e enviada como
Bearer. O seletor `OBS_LLM_PROVIDER` foi removido: LangChain é o único provedor.
Sem URL, modelo ou chave, `diagnose` termina com uma mensagem de configuração.
O provedor precisa aceitar `messages` e `response_format: {"type":"json_object"}`
e retornar `choices[0].message.content`. Outros protocolos exigem um adaptador.
Em Docker Desktop, uma API no computador pode ser acessada por
`host.docker.internal` em vez de `localhost`.

A LLM recebe o contexto selecionado e o schema de resposta. Não recebe a chave
como parte do prompt, o banco inteiro, comandos Docker ou o registro experimental.
A resposta passa por validação de schema e de todas as referências a evidências.
Há no máximo uma nova tentativa para corrigir saída inválida; falha de transporte
é registrada sem fallback de diagnóstico por regras.

## Integração com LangChain

O fluxo em `app/monitoring/providers.py` utiliza:

1. `ChatPromptTemplate` para compor instruções, schema e contexto.
2. `init_chat_model` com a integração `langchain-openai` para o protocolo Chat Completions.
3. Uma cadeia `prompt | modelo | StrOutputParser`, executada com `ainvoke`.
4. O texto retornado segue para a validação Pydantic e dos `evidence_ids` no diagnóstico.

A resposta bruta e os erros permanecem no histórico; a validação ocorre depois
da cadeia para permitir auditoria inclusive de respostas inválidas. Os retries
automáticos do SDK estão desativados. O diagnóstico controla a única tentativa
adicional para corrigir uma resposta inválida.

O uso de `langchain-openai` identifica o protocolo atual; não fixa o modelo nem
o servidor. Campos específicos de outros provedores e APIs em outro formato
exigem a integração correspondente. As execuções deste adaptador são registradas
com `provider: langchain`.

Referências: [modelos no LangChain](https://docs.langchain.com/oss/python/langchain/models)
e [integração ChatOpenAI](https://docs.langchain.com/oss/python/integrations/chat/openai).

## Demonstração prática

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -B experiments\demonstrate.py
```

O script executa sucesso → parada de Users → recuperação, verificando HTTP,
correlação, snapshot atual, histórico e persistência do diagnóstico. Users e o
coletor são restaurados no bloco de finalização. Execute no ambiente de demonstração.

O roteiro sempre exige diagnóstico real e verifica os resultados das três etapas.
`--port` permite alterar a porta do Gateway e `--project` seleciona o projeto Compose.
Cada execução cria uma pasta própria em `docs/evidencias/`, com relatório Markdown
e JSONs de cada etapa. O controle experimental fica em arquivo separado.

## Comandos de investigação

```powershell
docker compose run --rm --no-deps diagnostics context --service gateway --request-id req-demo-123
docker compose run --rm --no-deps diagnostics evidence ID_DA_EVIDENCIA
docker compose run --rm --no-deps diagnostics run ID_DA_EXECUCAO
docker compose logs --tail 30 collector
```

`context` mostra exatamente as evidências e os metadados entregues à LLM.
`evidence` retorna também `ingested_at`, separado do timestamp do evento.
`run` retorna solicitação, contexto, tentativas, respostas brutas e resultado.
`history` lista as vinte execuções mais recentes.

## Organização

```text
app/microservices/            APIs Gateway, Orders e Users, cliente HTTP e middleware
app/monitoring/               Coleta, histórico, contexto e diagnóstico LangChain
app/migrations/               Schema versionado com Alembic
app/config.py                 Configuração dos serviços e do monitoramento
app/models.py                 Contratos HTTP e logs estruturados
app/telemetry.py              Emissão de logs e correlação de requisições
app/cli.py                    Interface de investigação
tests/                        Testes unitários e de integração
experiments/demonstrate.py    Cenário automatizado de falha e recuperação
docs/                         Caso de uso, roteiro e registros
```

O Compose executa as migrações antes do coletor. Os volumes existentes são
preservados. Logs JSONL são ingeridos somente dos três nomes de arquivo conhecidos;
checkpoint e inclusão dos eventos participam da mesma transação. A chave
`/observability/snapshot/current` expira após 30 segundos sem publicação.
O histórico é gravado antes de publicar no etcd, preservando dados se este falhar.

## Configuração e limites

`GATEWAY_PORT`, `USERS_PORT`, `ORDERS_PORT`, `ETCD_PORT` e `ETCD_PEER_PORT`
alteram as portas. `HTTP_TIMEOUT_SECONDS` controla o timeout entre serviços.
`OBS_INTERVAL_SECONDS` controla a coleta e `OBS_SNAPSHOT_TTL_SECONDS` deve ser
maior que o intervalo. Para execução Python fora do Compose, use também
`OBS_DATABASE_URL`, `OBS_ETCD_URL`, `OBS_GATEWAY_URL`, `OBS_USERS_URL`,
`OBS_ORDERS_URL` e `OBS_LOG_DIR`.

O contexto permite até 80 evidências e 50.000 caracteres por padrão, com
`truncated` e `omitted_count`. Datas são normalizadas em UTC. Métricas ausentes
são `null`. RSS e threads são do processo; CPU e memória do sistema correspondem
ao ambiente visível ao processo, podendo refletir a VM do Docker.

Esta versão usa dados de negócio em memória, um coletor e um único membro etcd.
Não inclui autenticação de produção, política de retenção ou rotação automática
dos logs. As dependências têm faixas de versões, sem lockfile; registre versões
ao executar uma avaliação comparativa. A validade do schema e dos IDs não comprova
correção semântica do diagnóstico: isso pertence à avaliação formal posterior.

## Verificações

```powershell
.\.venv\Scripts\python.exe -B -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
```

Python 3.12+; imagem Docker Python 3.12. Os testes automatizados usam SQLite
temporário e transportes simulados. A demonstração usa PostgreSQL, etcd e HTTP
reais em containers e exige credenciais de LLM. O campo `simulated` é mantido
para leitura dos registros antigos; os novos diagnósticos usam LangChain.
