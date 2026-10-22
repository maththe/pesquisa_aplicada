# PBL 8 — DSR Etapa 5: melhorias do artefato

> Evolução posterior: o [agente com ferramentas e política](agente-ia.md) foi
> implementado após os registros locais da versão 2 abaixo. Sua integração foi
> testada com provedor simulado; a execução real depende das credenciais.


## Problema e objetivo do refinamento

A versão anterior demonstrava diagnóstico na consulta Gateway → Orders → Users.
Não havia uma compra interativa, preservação de carrinho, pagamento ou aviso de
recuperação. A avaliação histórica de setembro demonstrou viabilidade do
pipeline de diagnóstico, mas não avaliou continuidade da intenção de compra.

A versão 2 adiciona um cenário de loja executável na Vercel, sem depender de
uma VPS, para investigar: **como limitar o impacto percebido de uma falha de
pagamento, preservando a intenção de compra e a rastreabilidade do incidente?**

O objetivo é demonstrar mecanismos e coletar evidências. Não se afirma redução
medida de abandono, receita perdida ou tempo humano de investigação.

## Melhorias implementadas

| Limitação anterior | Alteração | Verificação |
| --- | --- | --- |
| Apenas consulta de pedido fictício | Catálogo, carrinho e finalização de teste | Total validado no servidor e comprovante de sandbox |
| Ausência de persistência da intenção | Carrinho em localStorage | Recarregamento preserva produtos e quantidades |
| Repetição de chamadas em falha conhecida | Circuit breaker na orquestração do navegador | Circuito aberto impede nova chamada de finalização |
| Erro pouco compreensível ao comprador | Mensagem contextual com preservação dos itens | Adição ao carrinho continua durante HTTP 503 |
| Sem acompanhamento da recuperação | Consentimento e aviso interno por incidente | Duas sondagens funcionais antes da liberação; um aviso |
| Falhas de naturezas distintas | Cenários HTTP 503, 504 e 402 separados | Recusa não abre circuito; timeout exige consulta |
| Reenvio ambíguo após timeout | Tentativa salva antes da requisição e reconciliação | Nova tentativa bloqueada até consulta do resultado |
| Dependência de Docker para toda apresentação | Funções Node serverless sem dependências externas | Página e API HTTP exercitadas no navegador |
| Difícil inspeção da evolução | Linha do tempo, IDs, avaliação e exportação | Três relatórios locais com resultados observados |
| Possível confusão entre IA e regras | Identificação explícita do modo | Padrão “Por regras · sem IA”; endpoint opcional de LLM |

O código anterior permanece disponível no controlador Python e em
`presentation/docker.html`; sua infraestrutura PostgreSQL/etcd não foi
substituída silenciosamente por armazenamento de produção. São dois modos de
execução com escopos distintos.

## Arquitetura e decisões

A Vercel serve HTML autossuficiente e as funções `/api/payments` e
`/api/diagnose`. O sandbox de pagamento valida produtos, quantidades e preços
no servidor. O cenário é enviado por requisição e afeta apenas o visitante;
selecionar “falha” não derruba infraestrutura compartilhada.

O carrinho, o estado do circuito, os avisos e as evidências são locais ao
navegador. O circuito é uma regra técnica do orquestrador da demonstração;
a LLM não bloqueia compras, executa comandos ou repara serviços. A API também
retorna erro quando a finalização solicita o cenário indisponível. Não existe
um bloqueio global confiável para clientes arbitrários: isso exigiria estado
central e um backend de produção.

O aviso exige consentimento e é exibido dentro da aplicação. Não é e-mail,
WhatsApp ou push em segundo plano. Retomar a compra exige ação do comprador.

O comprovante é derivado da chave da tentativa e do carrinho canônico. Repetir
a mesma entrada produz o mesmo identificador de sandbox. Isso **não comprova
idempotência financeira nem persistência transacional**: não existe provedor
financeiro ou livro de transações. O cenário 504 modela resposta ambígua e
permite praticar a consulta da mesma tentativa, sem efetuar cobrança.

## Avaliação preliminar observada

Em 22/10/2026 foram executadas três rodadas locais via Chromium, usando os
mesmos handlers HTTP que serão hospedados na Vercel: 8 verificações por rodada,
24 aprovações e nenhuma reprovação. Também foram exercitados recarregamento,
consentimento persistido, retomada da compra, reconciliação e layout móvel.

Os registros estão em [evidências da versão 2](evidencias/nexo-serverless-20261022/resumo.json),
com relatórios completos e capturas. São evidências de execução **local**,
não confirmação do deploy público. A janela temporal e os eventos específicos
estão nos JSONs; latências incluem apenas essas execuções no ambiente usado.

A comparação técnica da avaliação é: uma tentativa sem circuito já aberto
recebe HTTP 503 e preserva o carrinho; com o circuito aberto, uma nova tentativa
é recusada pelo orquestrador sem chamada de pagamento. Essa comparação prova
a condição testada, não economia global de chamadas em carga real.

## Limitações e próximo ciclo DSR

- Persistência restrita ao navegador/dispositivo; limpar os dados remove carrinho
  e evidências. Não há sincronização entre abas nem autenticação de compradores.
- Pagamento e falhas são controlados. O 504 é uma resposta de teste, não uma
  medição de timeout de um provedor financeiro.
- Avisos são internos e dependem de recuperação acionada/verificada na aplicação.
- A análise padrão é por regras. A LLM opcional requer configuração no backend;
  a avaliação desta versão não utilizou LLM nem mede sua acurácia.
- A reconciliação é determinística no sandbox. Em produção exige consulta ao
  provedor, ledger persistente, autenticação e idempotência transacional.
- Futuros ciclos devem comparar diagnóstico humano com/sem IA, ampliar tipos
  de incidente, repetir cenários sob carga e adotar critérios semânticos.

Assim, o refinamento entrega uma instância visual avaliável da continuidade de
compra, preservando os limites do que foi realmente observado.
