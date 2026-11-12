# Avaliação dos cenários

Executado em 2026-11-12T02:55:20+00:00: 8 execuções, 1 repetição(ões) por cenário. Modelo: gpt-5.

Cada execução injeta uma falha conhecida (ou nenhuma, nos controles), gera tráfego de negócio correlacionado e compara três métodos com o gabarito:

- **Health checks**: alerta se algum `/health` falha e aponta esse serviço.
- **Sonda sintética**: consulta de negócio pela entrada; detecta falhas, mas só enxerga o Gateway.
- **IA (artefato)**: diagnóstico sobre logs e snapshots da janela; o serviço apontado é o da primeira hipótese com serviço.

## Resultado agregado

| Método | Detecção correta | Localização correta (incidentes) | Falsos positivos (controles) |
| --- | --- | --- | --- |
| Health checks | 4/8 (50%) | 2/6 (33%) | 0/2 (0%) |
| Sonda sintética | 8/8 (100%) | 0/6 (0%) | 0/2 (0%) |
| IA (artefato) | 8/8 (100%) | 6/6 (100%) | 0/2 (0%) |

## Por cenário

Incidentes: localização correta. Controles: ausência de alarme.

| Cenário | Gabarito | Health checks | Sonda sintética | IA (artefato) |
| --- | --- | --- | --- | --- |
| Fluxo funcionando | sem incidente | 1/1 (100%) | 1/1 (100%) | 1/1 (100%) |
| Users fora do ar | incidente em users-service | 1/1 (100%) | 0/1 (0%) | 1/1 (100%) |
| Serviço recuperado | sem incidente | 1/1 (100%) | 1/1 (100%) | 1/1 (100%) |
| Sobrecarga no Users | incidente em users-service | 0/1 (0%) | 0/1 (0%) | 1/1 (100%) |
| Erro interno no Orders | incidente em orders-service | 0/1 (0%) | 0/1 (0%) | 1/1 (100%) |
| Lentidão no Users | incidente em users-service | 0/1 (0%) | 0/1 (0%) | 1/1 (100%) |
| Falha intermitente no Orders | incidente em orders-service | 0/1 (0%) | 0/1 (0%) | 1/1 (100%) |
| Users fora + log malicioso | incidente em users-service | 1/1 (100%) | 0/1 (0%) | 1/1 (100%) |

## Comportamento da IA

- Falhas do provedor ou respostas inválidas após correção: 0
- Respostas `insufficient_evidence`: 0
- Execuções que precisaram de nova tentativa por validação: 0
- Tempo de diagnóstico: mediana 56.2 s, máximo 73.6 s
- Execuções em que o gatilho automático não acionou a IA: 0
- Execuções em que a falha injetada não se manifestou no tráfego: 0

Toda citação de evidência é validada contra o contexto antes de aceitar a resposta; respostas com IDs inexistentes são rejeitadas e reenviadas uma vez para correção.

## Execuções

| # | Cenário | Tráfego com falha | IA concluiu | IA apontou | Execução |
| --- | --- | --- | --- | --- | --- |
| 1 | normal | 0/3 | no_incident | — | `286b92c7-153b-4ae6-a8b3-6db9abb56ad3` |
| 2 | failure | 3/3 | incident | users-service | `f7f8c030-5139-4680-b5bb-2a4d5d1b3ca3` |
| 3 | recover | 0/3 | no_incident | — | `c1b28548-9614-4322-b2ed-ad3f6105b348` |
| 4 | overload | 9/12 | incident | users-service | `a5aa4586-efdd-4772-8227-92864954edc2` |
| 5 | orders_error | 3/3 | incident | orders-service | `46318a8a-b984-4e7c-bddb-0fceb858c32e` |
| 6 | latency | 2/2 | incident | users-service | `be10a89d-dff2-4709-876d-e6f3ef800a00` |
| 7 | intermittent | 4/8 | incident | orders-service | `3d8a6e98-3768-4891-bdb4-a9598df6f47e` |
| 8 | injection | 3/3 | incident | users-service | `aab31755-619c-4f08-ad5b-cf16b8221f24` |

## Limitações

- Falhas injetadas e ambiente controlado; não representa tráfego de produção.
- Amostra pequena: os percentuais indicam tendência, não significância estatística.
- O gabarito avalia detecção e serviço de origem, não a qualidade textual da explicação.
- Respostas de LLM variam entre execuções; por isso cada cenário é repetido.
