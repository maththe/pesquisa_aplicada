# Publicar e executar na Vercel

Para o modo com ferramentas e ações do agente, consulte [Agente IA](agente-ia.md).
A tela inicia em **Regras**, com os cenários disponíveis sem LLM. O modo **Agente IA** fica disponível quando o servidor está configurado.

A versão 2 funciona sem VPS: HTML e funções Node de pagamento sandbox ficam na
Vercel. Não usa banco, Docker ou Neon para a demonstração de compra. Carrinho,
circuito, avisos e evidências ficam no navegador. Pagamentos não são reais.

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
Nesse comando antigo, o link secundário `docker.html` não é copiado: usar o novo
build para disponibilizar também essa página. As funções `api/*.mjs` precisam
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

`docker.html` mantém o painel anterior. Esse modo continua exigindo backend com
Docker, HTTPS, `PRESENTATION_API_TOKEN` e `PRESENTATION_ALLOWED_ORIGINS` com a
origem exata autorizada. Seu controlador é `python presentation/app.py` na raiz
do repositório; é separado das funções serverless. A chave da LLM nunca deve
ser gravada no HTML. A página Nexo não precisa desse backend externo.
