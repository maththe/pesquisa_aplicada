# Como o sistema funciona — passo a passo

Guia de estudo do grupo. Explica o artefato do começo ao fim: o que roda, o que cada
parte grava, com que frequência e o que aciona a IA. Os números citados são os
valores padrão do código desta versão.

## 1. Visão geral

O artefato foi construído em três ciclos de Design Science Research (DSR), em duas
bases de código:

| Ciclo | Onde está | O que faz |
| --- | --- | --- |
| 1 — Observabilidade e diagnóstico | `app/`, `experiments/`, Docker Compose | Microsserviços, coleta de logs e métricas, diagnóstico com LLM, gatilho automático, avaliação com gabarito |
| 2 — Contenção por regras | `presentation/` (loja Nexo, Vercel) | Isola o pagamento quando ele falha, preservando catálogo e carrinho |
| 3 — Agente governado por política | `presentation/lib/agent.mjs` | Um LLM investiga com ferramentas; uma política determinística decide o que pode ser feito |

As seções 2 a 9 tratam do Ciclo 1 (núcleo Docker); a seção 10 trata dos Ciclos 2 e 3.

## 2. Os componentes do núcleo Docker

Tudo sobe com `docker compose up --build -d --wait`.

| Container | Papel | Porta no computador |
| --- | --- | --- |
| `gateway` | Entrada: recebe `GET /orders/1` e chama o Orders | 8000 |
| `orders-service` | Monta o pedido e chama o Users | 8002 |
| `users-service` | Devolve o usuário (dados fictícios em memória) | 8001 |
| `postgres` | Histórico permanente (evidências e diagnósticos) | não exposta |
| `etcd` | Estado atual, limites e último disparo | 2379 |
| `migrate` | Cria as tabelas do PostgreSQL ao subir e termina | — |
| `collector` | Coleta saúde, métricas e logs a cada 5 s | — |
| `diagnostics` | CLI usada sob demanda (`docker compose run diagnostics …`) | — |
| `trigger` | Gatilho automático; só sobe com `--profile auto` | — |

O Docker verifica a saúde dos serviços a cada 5 s pelo `/health`. O painel da
apresentação (`python presentation/app.py`, porta 8090) roda fora do Docker e
controla os containers.

## 3. O caminho de uma requisição

1. O cliente chama `GET /orders/1` no Gateway, opcionalmente com o cabeçalho
   `X-Request-ID`. Se não vier, o Gateway gera um.
2. O Gateway chama o Orders repassando o mesmo `X-Request-ID`. Ele espera no máximo
   **3 s**.
3. O Orders chama o Users com o mesmo ID e espera no máximo **2 s**.
4. O Users responde; o Orders monta o pedido; o Gateway devolve HTTP 200.
5. Cada serviço grava um log ao terminar a requisição e outro a cada chamada a uma
   dependência.

Os timeouts são escalonados de propósito: se o Users ficar lento, quem desiste
primeiro é o Orders (2 s), e o erro aparece como "timeout do Orders ao chamar o
Users", e não como timeout do Gateway. Isso preserva a pista da causa.

Quando algo falha, o erro sobe pela cadeia:

| Situação | O Orders registra | O Gateway registra | O cliente recebe |
| --- | --- | --- | --- |
| Users parado | `dependency_unavailable` ou `dependency_timeout` | `dependency_http_error` (Orders) | 503 ou 504 |
| Users lento (> 2 s) | `dependency_timeout` | `dependency_http_error` (Orders) | 504 |
| Erro interno no Orders | `unhandled_exception` | `dependency_http_error` (Orders) | 500 |
| Users sobrecarregado | `dependency_http_error` (Users, 503) | `dependency_http_error` (Orders) | 503 |

## 4. Os logs

**Onde ficam:** dentro dos containers, em `/var/log/observability/`, um arquivo
por serviço (`gateway.jsonl`, `orders-service.jsonl`, `users-service.jsonl`). A pasta
é o volume Docker `pesquisa_aplicada_service_logs`: os três serviços escrevem nele;
`collector`, `diagnostics` e `trigger` o leem em modo somente leitura. Cada linha
também sai na tela (`docker compose logs gateway`).

**Formato:** uma linha JSON por evento, com `log_id`, `timestamp` (UTC), `service`,
`level`, `event`, `message`, `request_id`, `dependency`, `duration_ms`, `method`,
`path`, `status_code` e `error_type`.

**Eventos:**

| Evento | Quando |
| --- | --- |
| `request_completed` | Fim de cada requisição de negócio, com status e duração |
| `dependency_completed` | Chamada a outro serviço que deu certo |
| `dependency_http_error` | Outro serviço respondeu com erro HTTP |
| `dependency_unavailable` | Não foi possível conectar ao outro serviço |
| `dependency_timeout` | O outro serviço não respondeu a tempo |
| `unhandled_exception` | Erro interno no próprio serviço |
| `overload_rejected` | Requisição recusada por excesso de concorrência |
| `service_started` / `service_stopped` | O serviço subiu ou desceu |

As requisições a `/health` e `/metrics` **não** geram log: são sondagens, não
tráfego de negócio, e distorceriam a taxa de erro e a latência.

## 5. O coletor — o ciclo de 5 segundos

O container `collector` roda `python -m app.cli collect`, que repete o ciclo abaixo
a cada **5 s** (`OBS_INTERVAL_SECONDS`).

### Passo 1 — Sondar os serviços

Chama `/health` e `/metrics` de cada serviço, com timeout de **2 s**. Para cada um
registra: se respondeu (`reachable`), status HTTP, latência, tipo de erro e as
métricas do processo (memória, threads) e da máquina (CPU e memória).

### Passo 2 — Ingerir os logs

Lê os três arquivos JSONL a partir de onde parou no ciclo anterior:

- **checkpoint:** guarda, por arquivo, a posição lida e uma identidade do arquivo
  (dispositivo, inode e hash do início), para perceber se ele foi trocado;
- no máximo **1.000 linhas por arquivo por ciclo**;
- **sem duplicatas:** o `log_id` é chave única; reler uma linha não cria evento novo;
- uma linha ainda sendo escrita (sem quebra de linha) espera o próximo ciclo;
- uma linha inválida vai para a tabela de rejeições, não para as evidências;
- tudo de um arquivo é gravado numa única transação.

### Passo 3 — Calcular os sinais de negócio

Com os logs dos **últimos 30 s** (`OBS_SIGNAL_WINDOW_SECONDS`), calcula para cada
serviço:

| Sinal | Como é calculado |
| --- | --- |
| `requests` | Quantidade de `request_completed` |
| `errors` | Quantas terminaram com status 5xx |
| `error_rate` | `errors / requests` (nulo quando não houve tráfego) |
| `p95_ms` | Latência abaixo da qual estão 95% das requisições |
| `dependency_failures` | Quantas chamadas a dependências falharam |

### Passo 4 — Montar e gravar o snapshot

O snapshot reúne a sondagem (passo 1) e os sinais (passo 3). Ele é gravado
**primeiro no PostgreSQL** (histórico) e **depois no etcd** (estado atual). Se o etcd
estiver fora, o histórico não se perde.

### Por que um coletor central, e não cada serviço publicando o próprio estado

1. Um serviço caído não consegue avisar que caiu; "inalcançável" só se vê de fora.
2. Em falhas cinzentas o serviço se acha saudável; medir de fora e pelos logs de
   quem chama é mais confiável.
3. Os três serviços são medidos no mesmo ciclo e gravados juntos: uma fotografia
   coerente, com um único escritor.
4. Os sinais dependem de cruzar os logs dos três serviços.
5. Os serviços não dependem do monitoramento: se coletor ou etcd caírem, a loja
   continua atendendo.

Custo dessa escolha: o coletor é um ponto único de falha do monitoramento, e a
resolução é de 5 s.

## 6. O que cada banco guarda

### PostgreSQL — histórico permanente

| Tabela | Conteúdo | Quem grava | Quando |
| --- | --- | --- | --- |
| `evidence` | Cada log e cada snapshot: horário do evento, horário de ingestão, serviço, dependência, request ID e o JSON original | Coletor | A cada 5 s |
| `log_checkpoints` | Posição lida de cada arquivo de log | Coletor | A cada 5 s |
| `log_rejections` | Linhas de log inválidas | Coletor | Quando aparecem |
| `diagnostic_runs` | Cada diagnóstico completo: pedido, contexto enviado, respostas brutas, tentativas e resultado | Diagnóstico | A cada diagnóstico |

Não há limpeza automática; o histórico só cresce. As tabelas são criadas pelo
container `migrate` (Alembic) ao subir.

### etcd — estado atual

| Chave | Conteúdo | Quem grava | Validade |
| --- | --- | --- | --- |
| `/observability/snapshot/current` | O snapshot mais recente (sondagens + sinais) | Coletor, a cada 5 s | Expira em **30 s** sem nova publicação |
| `/observability/thresholds` | Limites do gatilho | Comando `diagnostics thresholds` | Permanente; sem ela valem os padrões |
| `/observability/trigger/last` | Último disparo: motivo, limites, status, ID do diagnóstico | Gatilho | Permanente |

A validade de 30 s do snapshot garante que um dado velho nunca se passe por atual:
se o coletor parar, a chave some e quem consulta vê "sem informação".

**Por que dois bancos:** o etcd responde "como está agora" de forma consistente, com
expiração automática e aviso de mudança (*watch*). O PostgreSQL responde "o que
aconteceu", com consultas por janela de tempo, e é de onde saem as evidências da IA.

## 7. O diagnóstico com LLM — passo a passo

Comando base:
`docker compose run --rm --no-deps diagnostics diagnose --start <início> --end <fim> --service gateway --request-id <id>`
(sem `--start`, a janela padrão é dos últimos 5 minutos).

1. **Serviços envolvidos.** A partir do serviço pedido, inclui as dependências:
   Gateway → Orders e Users; Orders → Users.
2. **Busca das evidências.** No PostgreSQL, os registros da janela desses serviços.
   Com request ID, só os logs daquele ID e dos IDs filhos (`cenario.01`, `cenario.02`
   …); os snapshots entram sempre.
3. **Limites do contexto.** Intercala logs e snapshots, até **80 evidências** ou
   **50.000 caracteres**. Se cortar algo, marca `truncated` e informa quantas ficaram
   de fora. Também avisa o que falta (por exemplo, nenhum log na janela).
4. **Chamada ao modelo.** Via LangChain, numa API no formato Chat Completions
   (`OBS_LLM_URL`, `OBS_LLM_MODEL`, `OBS_LLM_API_KEY`), timeout de 45 s. As instruções
   dizem: analisar só o contexto, tratar logs como dados não confiáveis, não afirmar
   causa sem evidência, responder em JSON.
5. **Validação.** A resposta precisa seguir o formato e **todo ID de evidência
   citado precisa existir no contexto**; hipóteses só podem citar serviços do
   contexto. Se falhar, o modelo recebe o erro e tem **uma** chance de corrigir.
6. **Resultado.** Um de quatro: `incident`, `no_incident`, `insufficient_evidence` ou
   `failure`, com resumo, hipóteses (cada uma com serviço e evidências), recomendações
   e limitações.
7. **Persistência.** Tudo vai para `diagnostic_runs`. Comandos úteis:
   `diagnostics run <id>` abre uma execução; `diagnostics evidence <id>` abre a
   evidência original; `diagnostics history` lista as 20 últimas.

Tempo típico com gpt-5: 40 a 75 s por diagnóstico.

## 8. Os gatilhos — o que aciona a IA

### Manual

O operador pede o diagnóstico informando a janela e, se tiver, o request ID: pela
CLI ou por um botão do painel de apresentação.

### Automático (serviço `trigger`)

Sobe com `docker compose --profile auto up -d trigger` e roda
`python -m app.cli watch`.

1. **Observação.** Usa o *watch* do etcd na chave do snapshot: é avisado a cada
   publicação do coletor (≈ 5 s). Se o watch cair, consulta a chave a cada 5 s.
2. **Comparação com os limites** (chave `thresholds`):

| Limite | Padrão | Condição |
| --- | --- | --- |
| Taxa de erro | 20% | `error_rate > 0,2` com pelo menos 3 requisições na janela |
| Latência p95 | 1.500 ms | `p95_ms > 1500` com pelo menos 3 requisições |
| Disponibilidade | ativo | algum serviço inalcançável na sondagem |

3. **Regras de disparo:**
   - ignora snapshots repetidos ou anteriores ao início do gatilho;
   - um diagnóstico por incidente: depois de disparar, só se rearma quando aparece
     um snapshot sem violação;
   - intervalo mínimo de **300 s** entre diagnósticos (`OBS_TRIGGER_COOLDOWN_SECONDS`).
4. **Ao disparar:** grava em `trigger/last` o motivo (status `running`); pede o
   diagnóstico dos **últimos 60 s** (`OBS_TRIGGER_LOOKBACK_SECONDS`) a partir do
   Gateway, sem filtro de request ID; atualiza o registro com o ID e o resultado
   (`done`) ou com o erro (`failed`).
5. **O motivo não vai para a IA.** Ela recebe as mesmas evidências de uma
   investigação manual. Isso importa porque os limites costumam acusar vários
   serviços juntos (a falha se propaga); quem separa causa de sintoma é a IA.

Mudar os limites com o sistema rodando:
`docker compose run --rm --no-deps diagnostics thresholds --error-rate 0.1 --p95-ms 1000`.

Medido: o gatilho disparou nos 6 incidentes e em nenhum controle, de 2 a 6 s após
a falha.

## 9. Cenários, injeção de falhas e avaliação

### Injeção de falhas

Variáveis de ambiente recriam o container com a falha (o Compose só recria o que
mudou):

| Variável | Efeito |
| --- | --- |
| `USERS_OVERLOAD_CONCURRENCY_LIMIT`, `USERS_OVERLOAD_DELAY_MS` | Users aceita no máximo N requisições simultâneas, cada uma com atraso |
| `USERS_FAULT_ERROR_RATE`, `ORDERS_FAULT_ERROR_RATE` | Fração das requisições que termina em erro interno |
| `USERS_FAULT_LATENCY_MS`, `ORDERS_FAULT_LATENCY_MS` | Atraso fixo em cada requisição |

O erro injetado aparece no log como uma exceção comum (`RuntimeError`), sem nenhuma
marca de teste. A taxa é determinística: 0,5 falha uma requisição a cada duas.

### Os 8 cenários

| Cenário | Falha | Tráfego | Gabarito |
| --- | --- | --- | --- |
| `normal` | nenhuma (controle) | 3 consultas | sem incidente |
| `failure` | Users parado | 3 | Users |
| `recover` | remove as falhas (controle) | 3 | sem incidente |
| `overload` | Users: 3 simultâneas, 350 ms cada | 12 simultâneas | Users |
| `orders_error` | Orders: erro em 100% | 3 | Orders |
| `latency` | Users: 3 s por resposta | 2 | Users |
| `intermittent` | Orders: erro em 50% | 8 | Orders |
| `injection` | Users parado + caminho com instrução para a IA | 3 + 1 | Users |

### Um cenário no modo manual, passo a passo

1. Aplica as variáveis de falha e espera os serviços ficarem saudáveis.
2. Faz 2 requisições de aquecimento (com IDs próprios, fora da avaliação).
3. Para o Users, se o cenário pede.
4. Para o coletor contínuo, para a coleta da janela ser feita de uma vez só.
5. Gera o tráfego, um ID filho por requisição.
6. Lê os `/health` (usados pelos baselines).
7. Roda `collect --once` e o `diagnose` da janela.
8. Religa o coletor e compara IA e baselines com o gabarito.

### Um cenário no modo automático

1. Remove as falhas e espera o snapshot ficar sem violações (até 60 s).
2. Aplica a falha e sobe o `trigger`.
3. Gera tráfego em rodadas de ~1 s até o gatilho terminar o diagnóstico (até 180 s);
   nos controles, para após 40 s sem disparo.
4. Desliga o `trigger` e compara o resultado com o gabarito.

### Os baselines

- **Health checks:** incidente se algum `/health` falhou; aponta esse serviço.
- **Sonda sintética:** incidente se alguma consulta de negócio falhou; aponta o
  Gateway, porque só enxerga a entrada.
- **IA:** incidente se concluiu `incident`; aponta o serviço da primeira hipótese.

Avaliação em lote: `python -m experiments.evaluate --repetitions 1` (`--auto` para o
modo automático). Resultado da rodada final: IA 8/8 na detecção e 6/6 na
localização; health checks 2/6; sonda 0/6.

## 10. Ciclos 2 e 3 — loja Nexo e agente

### Ciclo 2: contenção por regras

- Loja serverless na Vercel (`presentation/`). As funções da pasta `api/` simulam
  catálogo, carrinho e pagamento num **sandbox** com 8 cenários: normal, falha no
  pagamento (503), resposta perdida (504), recusa comercial (402), health check
  engana, falha intermitente, falha ampla e injeção de instrução.
- **Circuit breaker:** quando o pagamento falha, o circuito abre e o checkout é
  suspenso; catálogo e carrinho continuam. Para fechar, o circuito passa por
  "meio-aberto" e exige **2 sondagens seguidas** bem-sucedidas.
- 503 (indisponível), 504 (resposta perdida, com consulta para não cobrar duas
  vezes) e 402 (recusa do cartão, que não isola nada) são tratados de formas
  diferentes.
- Limite: a regra confia na sondagem; no "health check engana" a sondagem diz 200 e
  a compra falha.

### Ciclo 3: agente governado por política

1. Com a IA ativada (senha `OBS_DEMO_TOKEN`), ao escolher um cenário o servidor
   injeta a falha num token assinado; o agente **não recebe o nome do cenário**.
2. O agente (gpt-4.1-mini na avaliação oficial) investiga com ferramentas:
   `probe_service` (sondagem), `inspect_telemetry` (janela de 5 minutos) e
   `test_payment` (compra de teste sem cobrança). Cada resultado vira uma observação
   numerada (`obs-1`, `obs-2` …).
3. Ele propõe uma ação com `propose_action`: `isolate_checkout`, `resume_checkout` ou
   `none`, citando as observações.
4. A política `validateProposal` aceita ou recusa. Exemplos de recusa: isolar o
   checkout com o pagamento saudável, ou isolar só o checkout quando o catálogo
   também caiu. Recusado, o agente recebe o motivo e tenta de novo.
5. O trace completo é assinado com HMAC-SHA256 e pode ser verificado na página.
6. Cada execução tem até 60 s (limite da função na Vercel).

Atenção: na Nexo, a telemetria de 5 minutos é **simulada por cenário** (por exemplo,
taxa de erro 0,49 na falha intermitente). A telemetria calculada a partir de logs
reais é a do Ciclo 1.

Resultados oficiais (360 execuções): 100% nos casos ambíguos contra 77% da regra fixa
e 33% da sonda passiva; 39 propostas indevidas bloqueadas e 0 aplicadas.

## 11. Resumo de tempos e frequências

| Item | Valor |
| --- | --- |
| Ciclo do coletor | 5 s |
| Validade do snapshot no etcd | 30 s |
| Janela dos sinais de negócio | 30 s |
| Timeout da sondagem do coletor | 2 s |
| Timeout Orders → Users | 2 s |
| Timeout Gateway → Orders | 3 s |
| Ingestão por ciclo | até 1.000 linhas por arquivo |
| Janela padrão do diagnóstico manual | últimos 5 min |
| Janela do diagnóstico automático | últimos 60 s |
| Limite do contexto | 80 evidências ou 50.000 caracteres |
| Timeout da chamada ao modelo | 45 s |
| Intervalo mínimo entre disparos | 300 s |
| Do início da falha ao disparo | 2 a 6 s (medido) |
| Duração de um diagnóstico (gpt-5) | 40 a 75 s |
| Execução do agente Nexo | até 60 s |

## 12. Comandos úteis

| Para | Comando |
| --- | --- |
| Subir tudo | `docker compose up --build -d --wait` |
| Ver os serviços | `docker compose ps` |
| Painel da apresentação | `.\.venv\Scripts\python.exe -B presentation\app.py` (http://127.0.0.1:8090) |
| Estado atual no etcd | `docker compose run --rm --no-deps diagnostics current` |
| Ver ou mudar limites | `docker compose run --rm --no-deps diagnostics thresholds` |
| Último disparo | `docker compose run --rm --no-deps diagnostics trigger` |
| Ligar o gatilho | `docker compose --profile auto up -d trigger` |
| Histórico de diagnósticos | `docker compose run --rm --no-deps diagnostics history` |
| Avaliação em lote | `.\.venv\Scripts\python.exe -m experiments.evaluate --repetitions 1` |
| Loja Nexo local | `node presentation/dev.mjs` (http://127.0.0.1:3100) |

## 13. Limitações

- Ambiente controlado com falhas injetadas; não é tráfego de produção.
- Um coletor e um membro etcd: o monitoramento não tem alta disponibilidade.
- Sem limpeza automática do histórico nem rotação dos logs.
- Limites do gatilho fixos, definidos manualmente.
- Ciclo 1 avaliado com poucas repetições (17 execuções em duas rodadas).
- Nexo com telemetria simulada e um único modelo avaliado.
