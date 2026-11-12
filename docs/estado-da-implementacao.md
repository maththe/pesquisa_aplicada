# Estado da implementação

> Este documento descreve o núcleo Docker original. A evolução serverless e sua
> avaliação estão em [PBL 8](pbl8-melhorias.md) e [PJBL 3](pjbl3-artefato.md).
> A cobertura histórica descrita abaixo não equivale à suíte Python atual de 13 testes.

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
| 14 | Correlação hierárquica (`cenario.01`, `cenario.02`) | Implementada; contexto busca o prefixo |
| 15 | Injeção de falhas por serviço e oito cenários com gabarito | Implementada (`experiments/scenarios.py`) |
| 16 | Avaliação em lote com baselines (health checks e sonda sintética) | Implementada; uma rodada registrada |
| 17 | Sinais de negócio no snapshot, limites no etcd e gatilho automático | Implementada (`trigger`, profile `auto`) |
| 18 | Interface web de apresentação, modos manual e automático | Implementada (`presentation/`) |

## Contratos preservados

- Valores desconhecidos permanecem null; datas possuem timezone e são normalizadas em UTC.
- etcd guarda o estado atual em `/observability/snapshot/current` (com lease para
  expiração), os limites em `/observability/thresholds` e o último disparo do
  gatilho em `/observability/trigger/last`. PostgreSQL mantém o histórico.
- O snapshot inclui, por serviço, taxa de erro, latência p95 e falhas de dependência
  dos últimos 30 s, calculadas a partir dos logs ingeridos.
- Sondagens `/health` e `/metrics` não são registradas como tráfego de negócio.
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
  ou diagnóstico alternativo baseado em regras. Os limites decidem apenas quando
  investigar; o motivo do disparo não é enviado à LLM.
- Resultados suportados: incident, no_incident, insufficient_evidence e failure.
- Há no máximo uma correção de saída inválida. As tentativas ficam preservadas.
- Logs de controle e rótulos experimentais permanecem fora do contexto da LLM.

## Verificação

A suíte local (24 testes) cobre sobrecarga, injeção de falhas, correlação por
prefixo, baselines e pontuação, sinais de negócio, limites, regras de disparo
(uma vez por incidente, rearme e intervalo mínimo) e o roteiro de demonstração.
Ruff, formatação e mypy estrito passam em todos os arquivos.

Os testes usam SQLite temporário e HTTP simulado. O roteiro
`experiments/demonstrate.py` verifica as integrações reais com PostgreSQL, etcd e
os três serviços, gerando registros em `docs/evidencias/`.
O campo `simulated` foi preservado para permitir a leitura de registros antigos.
Novos diagnósticos sempre utilizam LangChain com autenticação.

## Limites e pendências

- Examinar a adequação semântica das hipóteses geradas; o gabarito mede apenas
  detecção e serviço de origem.
- Ampliar a avaliação: uma rodada por cenário indica tendência, não taxa de acerto
  (ver `docs/avaliacao.md`).
- Limites do gatilho são fixos e definidos manualmente.
- Sem retenção/rotação automática, autenticação de produção ou alta disponibilidade.
- A ingestão lê os arquivos atuais conhecidos; uma rotação externa que remova
  linhas ainda não ingeridas pode perder eventos.
- CPU/memória do sistema representam o ambiente visível; RSS e threads são do processo.
- O limite do contexto é em caracteres, não em tokens específicos de cada modelo.
- Interrupção forçada do controlador pode exigir recuperação manual dos serviços.
