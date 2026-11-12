# Gatilho automático pelo etcd

Antes, o diagnóstico só acontecia quando alguém pedia (`diagnostics diagnose`).
Com o gatilho, o próprio sistema percebe que algo saiu do aceitável e aciona a IA.

## Fluxo

```text
serviços → logs JSONL → coletor (a cada 5 s)
                          ├─ histórico no PostgreSQL (evidências)
                          └─ snapshot no etcd: health + sinais de negócio
                                     │  watch do etcd
                                     ▼
                         gatilho compara com os limites (também no etcd)
                                     │  limite violado
                                     ▼
                         diagnóstico da janela recente → registro do disparo no etcd
```

## Sinais de negócio no snapshot

Health checks só dizem se o processo responde, e por isso não percebem sobrecarga,
erro de aplicação, lentidão ou falha intermitente. O coletor passou a calcular, por
serviço, a partir dos logs dos últimos 30 s (`OBS_SIGNAL_WINDOW_SECONDS`):

- requisições de negócio concluídas e quantas terminaram com 5xx (taxa de erro);
- latência p95;
- falhas ao chamar dependências.

As sondagens `/health` e `/metrics` do coletor não são registradas como tráfego de
negócio, para não distorcer esses números nem encher a janela de evidências.

## Limites

Ficam na chave `/observability/thresholds` do etcd e podem ser alterados com o
sistema rodando:

```powershell
docker compose run --rm --no-deps diagnostics thresholds
docker compose run --rm --no-deps diagnostics thresholds --error-rate 0.1 --p95-ms 1000
```

| Limite | Padrão |
| --- | --- |
| Taxa de erro | acima de 20%, com no mínimo 3 requisições na janela |
| Latência p95 | acima de 1500 ms |
| Serviço inalcançável | ativo |

## Disparo

O serviço `trigger` (`diagnostics watch`) usa o *watch* do etcd na chave do snapshot,
com uma sondagem de reserva a cada 5 s. Quando um snapshot viola algum limite:

1. grava em `/observability/trigger/last` o motivo (`running`);
2. pede o diagnóstico dos últimos 60 s (`OBS_TRIGGER_LOOKBACK_SECONDS`), sem filtro
   de correlação;
3. atualiza o registro com `run_id` e conclusão (`done`).

O motivo do alerta **não** é enviado à IA. Ela recebe as mesmas evidências de uma
investigação manual e precisa localizar a origem sozinha: os limites violados
costumam apontar vários serviços ao mesmo tempo (o erro do Orders aparece também
no Gateway).

Proteções de custo:

- um diagnóstico por incidente: o gatilho só se rearma após um snapshot sem violação;
- intervalo mínimo entre diagnósticos (`OBS_TRIGGER_COOLDOWN_SECONDS`, 300 s);
- o serviço está no profile `auto` e não sobe com `docker compose up`.

```powershell
docker compose --profile auto up -d trigger
docker compose logs -f trigger
docker compose run --rm --no-deps diagnostics trigger
docker compose stop trigger
```

## Na interface

Marque **Disparo automático pelo etcd** e clique num cenário. O botão só injeta a
falha e gera tráfego contínuo; o painel **Gatilho automático** mostra qual limite foi
violado, em quanto tempo, e o diagnóstico que veio dele. Nos controles, a IA não é
chamada e nenhum crédito é gasto.

## Validação

| Cenário | Gatilho | Tempo até disparar | IA |
| --- | --- | --- | --- |
| `normal` (111 consultas em 50 s) | não disparou | — | não acionada (correto) |
| `orders_error` | taxa de erro 47% em Gateway e Orders | 6,4 s | `incident`, origem Orders (correto) |

### Detecção pelos limites, sem chamar a IA

Cada cenário foi aplicado com tráfego contínuo, verificando se o snapshot do etcd
violava os limites (o que dispararia o gatilho):

| Cenário | Disparo esperado | Disparou | Tempo | Serviços que violaram |
| --- | --- | --- | --- | --- |
| `normal` | não | não | — | — |
| `failure` | sim | sim | 6,1 s | Users (inalcançável) |
| `recover` | não | não | — | — |
| `overload` | sim | sim | 4,6 s | Gateway, Orders e Users (taxa de erro) |
| `orders_error` | sim | sim | 2,3 s | Gateway e Orders (taxa de erro) |
| `latency` | sim | sim | 4,0 s | Gateway, Orders e Users (erro e p95) |
| `intermittent` | sim | sim | 2,6 s | Gateway e Orders (taxa de erro) |
| `injection` | sim | sim | 6,1 s | Users (inalcançável), Gateway e Orders |

O gatilho acertou os 8 casos, mas os limites sozinhos **não localizam** a origem:
na sobrecarga e na lentidão os três serviços violam ao mesmo tempo, porque a falha
se propaga pela cadeia. Os limites dizem *quando* investigar; separar causa de
sintoma continua sendo papel do diagnóstico.

Para rodar a avaliação em lote nesse modo:

```powershell
.\.venv\Scripts\python.exe -m experiments.evaluate --auto --repetitions 1
```

## Limitações

- Limites fixos, definidos manualmente; não há detecção de anomalia nem aprendizado
  do comportamento normal.
- Um único gatilho e um único membro etcd.
- Janela de 30 s: incidentes mais curtos que um ciclo de coleta podem passar.
