# Avaliação dos cenários

Executado em 2026-11-11T22:35:30-03:00: 9 execuções, 1 a 2 repetições por cenário. Modelo: gpt-5.

Cada execução injeta uma falha conhecida (ou nenhuma, nos controles), gera tráfego de negócio correlacionado e compara três métodos com o gabarito:

- **Health checks**: alerta se algum `/health` falha e aponta esse serviço.
- **Sonda sintética**: consulta de negócio pela entrada; detecta falhas, mas só enxerga o Gateway.
- **IA (artefato)**: diagnóstico sobre logs e snapshots da janela; o serviço apontado é o da primeira hipótese com serviço.

## Resultado agregado

| Método | Detecção correta | Localização correta (incidentes) | Falsos positivos (controles) |
| --- | --- | --- | --- |
| Health checks | 5/9 (56%) | 2/6 (33%) | 0/3 (0%) |
| Sonda sintética | 9/9 (100%) | 0/6 (0%) | 0/3 (0%) |
| IA (artefato) | 9/9 (100%) | 6/6 (100%) | 0/3 (0%) |

## Por cenário

Incidentes: localização correta. Controles: ausência de alarme.

| Cenário | Gabarito | Health checks | Sonda sintética | IA (artefato) |
| --- | --- | --- | --- | --- |
| Fluxo funcionando | sem incidente | 2/2 (100%) | 2/2 (100%) | 2/2 (100%) |
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
- Tempo de diagnóstico: mediana 42.7 s, máximo 63.1 s
- Execuções em que o gatilho automático não acionou a IA: 0
- Execuções em que a falha injetada não se manifestou no tráfego: 0

Toda citação de evidência é validada contra o contexto antes de aceitar a resposta; respostas com IDs inexistentes são rejeitadas e reenviadas uma vez para correção.

## Execuções

| # | Cenário | Tráfego com falha | IA concluiu | IA apontou | Execução |
| --- | --- | --- | --- | --- | --- |
| 1 | normal | 0/3 | no_incident | — | `fd0f6e6a-cc9c-4e3d-a04e-91c9667e3fe5` |
| 2 | failure | 3/3 | incident | users-service | `80b9bc8c-cbc2-4019-9a80-65a16f264d05` |
| 3 | recover | 0/3 | no_incident | — | `8bc4ed8b-e9e0-44d8-b2c8-b756272086eb` |
| 4 | overload | 9/12 | incident | users-service | `5b3c0084-3299-4efc-9cc9-c8032ad1a00f` |
| 5 | orders_error | 3/3 | incident | orders-service | `bea6dcf0-f9d4-414c-8b7c-ae95ecc90809` |
| 6 | latency | 2/2 | incident | users-service | `a4f295ed-a67b-4fa2-874a-c244fecc30bd` |
| 7 | intermittent | 4/8 | incident | orders-service | `ae2481c7-33dc-4387-adcf-3c505bbadffe` |
| 8 | injection | 3/3 | incident | users-service | `4a8f06c2-d251-4f44-aa4a-cb3b05bec842` |
| 9 | normal | 0/3 | no_incident | — | `d0d40643-1864-4d6d-83d3-a7898f5ce366` |

## Limitações

- Falhas injetadas e ambiente controlado; não representa tráfego de produção.
- Amostra pequena: os percentuais indicam tendência, não significância estatística.
- O gabarito avalia detecção e serviço de origem, não a qualidade textual da explicação.
- Respostas de LLM variam entre execuções; por isso cada cenário é repetido.
