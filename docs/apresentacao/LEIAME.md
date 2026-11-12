# Kit da apresentação

Material-base para os slides: prints, diagramas, tabelas e comprovações, todos
gerados em 12/11/2026 a partir do código desta versão e de execuções reais.

| Pasta | Conteúdo |
| --- | --- |
| `tabelas.md` | Todas as tabelas de resultado, com a fonte de cada número |
| `diagramas/` | 5 diagramas em PNG (2x) e o `diagramas.html` editável que os gera |
| `prints/docker/` | Painel do núcleo Docker: página inteira de cada cenário e recortes (`_placar`, `_gatilho`, `_diagnostico_ia`, `_health_e_trafego`, `_resultado`) |
| `prints/nexo/` | Loja Nexo: modo Regras (`nexo_01` a `nexo_11`) e modo Agente IA com trace (`nexo_ia_01` a `nexo_ia_03`) |
| `comprovacoes/` | Saídas de terminal (`.txt`) e as mesmas em imagem (`.png`): testes, qualidade, serviços, etcd, gatilho, evidência maliciosa |

## Origem dos dados

- **Painel Docker, cenários 1 a 8:** rodada final da avaliação
  (`docs/evidencias/avaliacao-20261112T025520Z-8f5599/`, gpt-5).
- **Painel Docker, modo automático (`9_` e `10_`):** disparo real do gatilho e
  execução persistida `3e064222-…`; latências de `/health` medidas ao gerar o print.
- **Nexo, modo Regras:** servidor local, sem IA.
- **Nexo, modo Agente IA:** 3 execuções reais com gpt-4.1-mini, cada uma com a
  página zerada. O número de 360 execuções vem da avaliação oficial, não destes prints.
- **Matriz DSR da página Nexo (`nexo_08`):** simulação por regras, **sem IA**. A
  coluna "Investigação Adaptativa" é uma regra que repete o canário; não confundir
  com o Agente IA.

## Roteiro sugerido (≈15 slides) e asset de cada um

| # | Slide | Mensagem | Assets |
| --- | --- | --- | --- |
| 1 | Título | Diagnóstico de falhas em sistemas distribuídos com IA governada | — |
| 2 | O problema | Health check verde, cliente sem pedido | `prints/docker/4_overload_health_e_trafego.png` |
| 3 | Pergunta e método | DSR (Hevner, Peffers) em 3 ciclos | `diagramas/03_ciclos_dsr.png` |
| 4 | Ciclo 1: arquitetura | Logs → coletor → etcd/PostgreSQL → IA com evidências | `diagramas/01_arquitetura_nucleo_docker.png` |
| 5 | Ciclo 1: como avaliamos | Falha conhecida, tráfego real, 3 métodos vs. gabarito | `diagramas/04_metodo_avaliacao_docker.png` |
| 6 | Ciclo 1: resultados | IA 8/8 e 6/6; health 2/6; sonda 0/6 | `tabelas.md` §1.1 e §1.2 |
| 7 | Exemplo: erro no Orders | Health verde, sonda vê o Gateway, IA aponta o Orders | `prints/docker/5_orders_error_placar.png`, `5_orders_error_diagnostico_ia.png` |
| 8 | Log malicioso | Instrução no log não muda o diagnóstico | `comprovacoes/10_evidencia_log_malicioso.png`, `prints/docker/8_injection_placar.png` |
| 9 | Gatilho automático | Limites no etcd decidem quando; IA decide onde | `diagramas/02_gatilho_automatico_etcd.png`, `prints/docker/9_auto_orders_error_gatilho.png`, `tabelas.md` §1.4 |
| 10 | Ciclo 2: Nexo por regras | Carrinho preservado; a sonda engana | `prints/nexo/nexo_04_health_check_engana_regras.png` + `nexo_10_health_check_engana_compra_loja.png` |
| 11 | Ciclo 3: agente governado | Modelo investiga; política autoriza | `diagramas/05_agente_governado_por_politica.png`, `prints/nexo/nexo_ia_02_falha_intermitente_trace.png` |
| 12 | Ciclo 3: 360 execuções | 100% nos ambíguos vs. 33% e 77% | `tabelas.md` §2.1 e §2.2 |
| 13 | Política (DP1) | 39 propostas indevidas bloqueadas, 0 aplicadas | `tabelas.md` §2.3, `prints/nexo/nexo_ia_03_injecao_prompt_minimo_politica_trace.png` |
| 14 | Princípios de design | DP1 política, DP2 canário + telemetria, DP3 cegamento e auditoria | `docs/dsr-consolidado.md` §5 |
| 15 | Rigor e reprodutibilidade | 24 + 57 testes, mypy estrito, evidências persistidas | `comprovacoes/01`, `02`, `03` |
| 16 | Limitações | Ambiente controlado, poucas repetições no Ciclo 1, limites fixos | `tabelas.md` §4 |
| 17 | Conclusão | Contribuições e próximos passos | — |

## Plano B ao vivo

Se a internet ou o provedor falharem, todos os slides acima já usam material gravado.
Para a demo ao vivo, ver `docs/caso-de-uso-apresentacao.md` (núcleo Docker) e
`docs/guia-do-projeto.md` §5 (Nexo).
