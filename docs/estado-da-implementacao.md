# Estado da implementação

A versão funcional reúne a aplicação distribuída, coleta, armazenamento e
interface de diagnóstico. A validação com uma LLM real depende do modelo,
endpoint e credencial do provedor escolhido.

| Fase | Entrega | Estado |
| --- | --- | --- |
| 1 | Arquitetura, componentes e lacunas | Implementada |
| 2 | APIs, logs JSON e request ID | Implementada |
| 3 | Coleta psutil/HTTPX e snapshots Pydantic | Implementada |
| 4 | Estado atual no etcd com etcd3gw | Implementada, com TTL |
| 5 | PostgreSQL, SQLAlchemy 2 e Alembic | Implementada |
| 6 | Histórico de snapshots e logs | Implementada |
| 7 | Consultas por janela UTC e request ID | Implementada |
| 8 | Context Builder com evidências, limites e truncamento | Implementada |
| 9 | Cadeia LangChain com URL, modelo e chave obrigatórios | Implementada; API real a configurar |
| 10 | Schema, evidence_ids e registro das tentativas | Implementada |
| 11 | CLI de estado, contexto, diagnóstico, evidências e histórico | Implementada |
| 12 | Integração com PostgreSQL, etcd e LangChain | Disponível no Compose e no roteiro automatizado |
| 13 | Cenário de falha com controlador experimental separado | Normal, indisponibilidade e recuperação |

## Contratos preservados

- Valores desconhecidos permanecem null; datas possuem timezone e são normalizadas em UTC.
- etcd guarda somente o estado atual em `/observability/snapshot/current`,
  com lease para expiração. PostgreSQL mantém o histórico.
- Logs têm checkpoint por arquivo, deduplicação por log_id e ingestão transacional.
  PostgreSQL serializa a atualização dos checkpoints com bloqueio transacional.
- Timestamp do evento e ingested_at são preservados separadamente.
- O contexto filtra a janela, request ID e serviço/dependências; intercala logs
  e snapshots, preservando o conteúdo e os IDs das evidências incluídas.
- Snapshots representam o conjunto monitorado. Ao filtrar um serviço, o contexto
  ainda inclui o snapshot original completo para manter sua integridade.
- Limites de itens e caracteres geram omitted_count e truncated.
- Rastreabilidade: DiagnosticRequest → DiagnosticContext → evidence_ids →
  LLMExecution → DiagnosticResponse.
- O provedor não recebe objetos de banco, etcd, Docker ou controle de falhas.
- Não há agentes, execução de recomendações, correção automática da aplicação
  ou diagnóstico alternativo baseado em regras.
- Resultados suportados: incident, no_incident, insufficient_evidence e failure.
- Há no máximo uma correção de saída inválida. As tentativas ficam preservadas.
- Logs de controle e rótulos experimentais permanecem fora do contexto da LLM.

## Verificação

A suíte local cobre as APIs originais e o pipeline novo, incluindo falha de
coleta, indisponibilidade do etcd, checkpoints, rotação, duplicatas, janela
temporal, truncamento, resposta inválida, referência inventada e reparo limitado.

Os testes usam SQLite temporário e HTTP simulado. O roteiro
`experiments/demonstrate.py` verifica as integrações reais com PostgreSQL, etcd e
os três serviços, gerando registros em `docs/evidencias/`.
O campo `simulated` foi preservado para permitir a leitura de registros antigos.
Novos diagnósticos sempre utilizam LangChain com autenticação.

## Limites e pendências

- Configurar e executar o provedor real informado pelo estudante.
- Examinar a adequação semântica das hipóteses geradas.
- Executar avaliação formal posterior, com cenários repetidos e critérios definidos.
- Sem retenção/rotação automática, autenticação de produção ou alta disponibilidade.
- A ingestão lê os arquivos atuais conhecidos; uma rotação externa que remova
  linhas ainda não ingeridas pode perder eventos.
- CPU/memória do sistema representam o ambiente visível; RSS e threads são do processo.
- O limite do contexto é em caracteres, não em tokens específicos de cada modelo.
- Interrupção forçada do controlador pode exigir recuperação manual dos serviços.
