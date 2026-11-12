# Publicar e executar na Vercel

Para o modo com ferramentas e ações do agente, consulte [Agente IA](agente-ia.md).
A tela inicia em **Regras**, com os cenários disponíveis sem LLM. O modo **Agente IA** fica disponível quando o servidor está configurado.

A versão 2 funciona sem VPS: HTML e funções Node de pagamento sandbox ficam na
Vercel. Não usa Docker ou Neon para a demonstração de compra. Carrinho,
circuito, avisos e evidências ficam no navegador; opcionalmente, os eventos do
servidor são gravados no Upstash Redis (seção "Logs salvos no servidor"). Pagamentos não são reais.

## Configuração

Importar `HenryMendesr/pesquisa_aplicada` e definir:

| Campo | Valor |
| --- | --- |
| Framework Preset | Other |
| Root Directory | `presentation` |
| Build Command | `node build.mjs` |
| Output Directory | `public` |
| Install Command | vazio |
| Node.js | 22.x |

`presentation/vercel.json` contém o build. Se houver overrides no painel, remover
ou atualizar os conflitantes. O `index.html` versionado é autossuficiente e também
funciona com o comando antigo `mkdir -p public && cp index.html public/index.html`.
As funções `api/*.mjs` precisam
ser detectadas como funções pela Vercel; não publique somente a pasta `public`
como upload estático.

Nenhuma variável é necessária para catálogo, carrinho, cenários, avaliação ou
análise por regras. Configurar uma LLM real é opcional e exige estas variáveis
**somente no servidor Vercel**:

- `OBS_LLM_URL`: endpoint HTTPS compatível com Chat Completions.
- `OBS_LLM_MODEL`: modelo aceito pelo provedor.
- `OBS_LLM_API_KEY`: chave do provedor, como variável sensível.
- `OBS_DEMO_TOKEN`: segredo aleatório de pelo menos 32 caracteres para autorizar
  consultas pagas à LLM. É informado pelo apresentador na interface e fica em
  memória na aba; não é incluído nos relatórios ou no código.

O endpoint valida IDs citados e não executa recomendações. Sem configuração ou
quando a chamada falha, a interface informa o problema e identifica a análise
por regras como **sem IA**. Não há diagnóstico real de LLM comprovado pela
avaliação serverless registrada no repositório.

## Logs salvos no servidor

Sem configuração, os eventos ficam apenas no navegador. Para guardá-los no
servidor, conecte um banco **Upstash Redis** pelo Marketplace da Vercel
(**Storage → Create Database → Upstash for Redis**) e vincule-o ao projeto.
A integração cria as variáveis abaixo (as antigas do Vercel KV também são aceitas):

| Variável | Alternativa aceita |
| --- | --- |
| `UPSTASH_REDIS_REST_URL` | `KV_REST_API_URL` |
| `UPSTASH_REDIS_REST_TOKEN` | `KV_REST_API_TOKEN` |

Faça um novo deploy depois de vincular. As funções gravam pela API REST do
Upstash, sem dependências npm. Cada evento recebe `id` e `at` (UTC):

| `type` | Origem | Conteúdo |
| --- | --- | --- |
| `payment` | `/api/payments` | operação, cenário, status HTTP, resultado, `attemptId`, comprovante, total, modo (`rules` ou `agent`) |
| `experiment` | `/api/experiment` | criação ou injeção, cenário, revisão e estado do checkout |
| `agent_run` | `/api/agent` | registro completo da execução (trace, observações, proposta, decisão da política, ação aplicada) e sua assinatura HMAC |
| `diagnosis` | `/api/diagnose` | evidências enviadas, resultado e `evidence_ids`, ou falha |

Não são gravados IP, tokens, chave do provedor nem itens do carrinho. Requisições
malformadas (HTTP 400) não são registradas. A lista guarda os **2.000 eventos mais
recentes** e expira 30 dias após o último evento. Um evento acima de 60 mil
caracteres é substituído por um marcador `truncated`. Se o Upstash estiver fora,
a requisição continua normalmente e o evento é perdido (espera máxima de 1,5 s).

Consultar os logs (exige o `OBS_DEMO_TOKEN`):

```bash
curl -H "Authorization: Bearer $OBS_DEMO_TOKEN" "https://SEU-PROJETO.vercel.app/api/logs?limit=50"
```

Filtros: `limit` de 1 a 2000 (padrão 100) e `type` (`payment`, `experiment`,
`agent_run` ou `diagnosis`). Sem Upstash, o endpoint responde HTTP 503 com
`configured: false`. Um `agent_run` lido daqui pode ser conferido enviando `run` e
`signature` para `/api/agent` com `operation: "verify"`.

## Verificar o deploy

Depois de implantar o commit:

1. Abrir a página e confirmar o título Nexo e o catálogo.
2. Adicionar um produto e finalizar no modo normal (HTTP 200).
3. Introduzir falha (HTTP 503), confirmar carrinho preservado e solicitar aviso.
4. Restaurar e verificar o aviso interno e a liberação da finalização.
5. Executar a avaliação: os oito resultados devem refletir as chamadas reais.
6. Exportar o relatório dessa execução pública. Não reutilizar um relatório
   local como prova de que o deploy funcionou.

Se `/api/payments` retornar HTML/404, conferir Root Directory e a inclusão das
funções `presentation/api`, em vez de alterar a interface para simular sucesso.

## Executar localmente

```bash
cd presentation
node build.mjs
node --test tests/*.test.mjs
node dev.mjs
```

O servidor de desenvolvimento serve a página e os mesmos handlers da Vercel.
Use o endereço local mostrado/configurado pelo servidor no seu navegador.

## Experimento original com Docker

O núcleo Docker tem painel próprio, servido localmente por
`python presentation/app.py` (`presentation/diagnostico.html`): oito cenários com
falhas injetadas, gatilho automático pelo etcd e placar com gabarito. Ele não é
publicado na Vercel, porque depende do Docker Compose local. A chave da LLM fica
no `.env` e nunca é gravada no HTML. A página Nexo não precisa desse backend.
O antigo `docker.html`, com controlador remoto por token, foi substituído por
esse painel local.
