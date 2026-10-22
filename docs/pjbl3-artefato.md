# PJBL 3 — Desenvolvimento do Artefato (RA2)

> Evolução posterior: o [agente com ferramentas e política](agente-ia.md) foi
> implementado após os registros locais da versão 2 abaixo. Sua integração foi
> testada com provedor simulado; a execução real depende das credenciais.


## Artefato e problema atendido

O projeto investiga falhas em sistemas distribuídos e seus efeitos na operação
percebida pelo usuário. O núcleo original correlaciona logs/métricas e oferece
diagnóstico com LangChain. A versão 2 acrescenta uma loja experimental para
mostrar o efeito da indisponibilidade de pagamento e a preservação da intenção
de compra.

O produto apresentado reúne catálogo, carrinho persistente local, pagamento
sandbox via API HTTP, circuito de proteção, recuperação verificada, aviso
consentido, linha do tempo e exportação de evidências. A interface é hospedável
na Vercel sem servidor próprio ou chave financeira.

## Construção

| Componente | Implementação |
| --- | --- |
| Interface | HTML/CSS e JavaScript, responsiva e sem bibliotecas externas |
| Orquestração | `presentation/lib/store.mjs`: carrinho, circuito, tentativas, avisos e eventos |
| Pagamento | `presentation/lib/payment.mjs` e `api/payments.mjs`: validação e cenários HTTP |
| Análise | Regras explicitamente identificadas; `api/diagnose.mjs` permite LLM opcional com autenticação |
| Build | `presentation/build.mjs`: HTML autossuficiente e saída estática |
| Ambiente local | `node presentation/dev.mjs`, sem instalação de pacotes |
| Testes | `node --test presentation/tests/*.test.mjs` e suíte Python existente |
| Artefato anterior | APIs FastAPI, PostgreSQL, etcd, coletor, CLI e controlador Docker preservados |

Na evolução DSR, a limitação da consulta isolada motivou a implementação do
cenário de compra. Os resultados locais alimentam a discussão de limitações e
uma próxima rodada de melhorias. Os enunciados completos de PBL4–PBL7 não estão
no repositório; não se presume uma associação específica além das etapas de
construção, demonstração e avaliação descritas no enunciado fornecido.

## Organização da interface

A página abre no laboratório, com resumo da avaliação, último HTTP do cenário,
estado da proteção e quantidade de evidências. Os oito testes e o mapa de
contenção são o foco principal. A loja fica recolhida em **Aplicação de apoio**,
usada para comprovar visualmente que o carrinho permanece disponível enquanto
a finalização está suspensa. O mapa identifica catálogo/carrinho como componentes
locais e pagamento como função HTTP sandbox; não representa containers reais.

## Roteiro de apresentação (8–12 minutos)

1. **Problema e arquitetura.** Explicar a falha de uma dependência de pagamento
   enquanto catálogo e carrinho continuam utilizáveis. Mostrar o aviso de sandbox.
2. **Avaliação e referência funcional.** Executar os oito testes e conferir os resultados.
   Abrir “Aplicação de apoio”, selecionar operação normal, adicionar um produto e
   finalizar. Mostrar HTTP 200, total e comprovante; não houve cobrança real.
3. **Incidente.** Adicionar outro produto e selecionar “Falha no pagamento”.
   Abrir a linha do tempo e localizar HTTP 503 e abertura do circuito.
4. **Impacto limitado.** Adicionar outro produto durante o incidente. Confirmar
   que a finalização está suspensa e o carrinho continua disponível.
5. **Consentimento e persistência.** Solicitar o aviso, recarregar a página e
   mostrar os itens e o pedido de aviso preservados.
6. **Recuperação.** Usar “Restaurar e verificar pagamento”. Mostrar as duas
   sondagens HTTP 200, circuito fechado e um único aviso interno. Finalizar
   somente após ação do comprador.
7. **Casos distintos.** Demonstrar HTTP 402 sem circuito aberto e HTTP 504 com
   consulta da tentativa pendente antes de nova finalização.
8. **Avaliação e evidências.** Executar a avaliação, conferir resultados e
   exportar o JSON. Abrir um ID citado na análise e localizar o evento original.
9. **Limites.** Explicar o estado local, a falha controlada e a diferença entre
   regras e LLM. Não apresentar análise por regras como IA real.

O modo opcional de LLM exige `OBS_LLM_URL`, `OBS_LLM_MODEL`, `OBS_LLM_API_KEY`
e `OBS_DEMO_TOKEN` nas variáveis do servidor Vercel. A chave do provedor nunca
vai para o frontend. Sem essas variáveis, os demais fluxos funcionam e a
interface identifica a análise por regras. Essa configuração não foi validada
com provedor real na avaliação da versão 2.

## Evidências de funcionamento e avaliação preliminar

A suíte Node executou 18 testes automatizados e a suíte Python executou 13,
todos aprovados na validação local. A avaliação local em Chromium executou três rodadas com oito verificações
funcionais cada, todas aprovadas. Foram adicionalmente verificadas persistência
após recarregamento, consentimento, aviso único, compra, reconciliação e ausência
de erros JavaScript e overflow em viewport móvel.

- [Resumo observado](evidencias/nexo-serverless-20261022/resumo.json).
- [Rodada 1](evidencias/nexo-serverless-20261022/relatorio-1.json).
- [Rodada 2](evidencias/nexo-serverless-20261022/relatorio-2.json).
- [Rodada 3](evidencias/nexo-serverless-20261022/relatorio-3.json).
- [Indisponibilidade](evidencias/nexo-serverless-20261022/01-indisponibilidade.png).
- [Avaliação](evidencias/nexo-serverless-20261022/02-avaliacao.png).
- [Visual móvel](evidencias/nexo-serverless-20261022/03-mobile.png).

Os relatórios registram resultados observados, datas, tentativas, IDs e eventos,
sem chaves. Resultados esperados não substituem reprovações. O botão de avaliação
usa carrinhos isolados e não altera o carrinho do apresentador.

Esse ensaio demonstra viabilidade funcional do sandbox. Não comprova segurança
para comércio real, disponibilidade contínua, durabilidade financeira, entrega
externa de notificações ou acurácia de IA. Os resultados históricos do núcleo
Docker/LLM de setembro continuam separados dos resultados atuais.

## Entrega

O código executável, o [registro de melhorias](pbl8-melhorias.md), este roteiro,
a [configuração da Vercel](vercel.md) e os registros anexos compõem a entrega.
O estado do deploy deve ser confirmado na Vercel pelo commit implantado e por
uma nova execução pública da avaliação; o sucesso local não o comprova.
