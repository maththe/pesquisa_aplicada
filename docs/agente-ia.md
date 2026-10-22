# Agente IA — investigação, política e ação

## O que mudou

A página abre com os testes por regras disponíveis. Em **Usar IA**, informe a
senha `OBS_DEMO_TOKEN` e clique em **Ativar IA**. Ao escolher um cenário ou
restaurar o pagamento, a interface injeta a condição e chama o agente na sequência.
A injeção não abre nem fecha o circuito: a ação depende das ferramentas escolhidas
pela LLM e da validação da política. **Analisar novamente** repete a análise.
Não existe provedor simulado ou fallback por regras nessa rota de produção.

A consulta inicial tem limite de seis segundos; conexão e injeção, oito segundos;
a execução do agente, cinquenta segundos. A barra de execução mostra a etapa e
permite cancelar. Erros aparecem na página e os controles são liberados. A senha
não é persistida; recarregar a página exige ativar a IA novamente.

A proteção defensiva do checkout e o benchmark funcional continuam existindo.
Quando essa proteção por regras atua, a origem aparece como **Regras**, nunca
como uma ação da IA. Os oito testes funcionais são independentes da execução do
agente; passar neles não demonstra qualidade de diagnóstico da LLM.

## Ciclo implementado

1. `/api/experiment` cria um experimento assinado. Só o apresentador autenticado
   pode injetar normalidade, indisponibilidade, timeout ou recusa.
2. `/api/agent` recebe a tarefa e o estado de isolamento. O rótulo da intervenção
   não é incluído nas mensagens ao modelo. O modelo recebe resultados quando
   pede uma ferramenta, não a resposta do controlador experimental.
3. A LLM pode chamar `probe_service` para catálogo, carrinho ou pagamento;
   `test_payment` executa uma transação canário sem cobrança no sandbox.
4. A LLM chama `propose_action` com uma ação tipada, justificativa curta e IDs
   observados. Texto livre não executa comandos.
5. A política valida escopo e referências. Propor não equivale a aplicar.
6. Só uma execução com proposta aceita e resposta final válida aplica a ação,
   atualiza o estado assinado e registra sua origem como agente.
7. A página mostra ferramentas, resultados, proposta, decisão da política e
   aplicação. O relatório exporta esse registro sem token de acesso ou chave.

As ferramentas chamam o **mesmo kernel de pagamento do sandbox**, dentro da
função serverless. O campo `transport: in_process_sandbox` identifica isso no
registro. Não são sondagens de containers externos. Catálogo/carrinho representam
os componentes desta demonstração, não processos independentes monitorados.

## Política

- `isolate_checkout`: exige verificações citadas dos três componentes, catálogo
  e carrinho disponíveis e uma verificação funcional de pagamento com 503/504.
- `resume_checkout`: exige checkout já isolado, dois resultados funcionais
  consecutivos 200/402, sondagens disponíveis e nenhuma tentativa pendente.
- `none`: mantém o estado. Exige investigação mínima e referências válidas.
- HTTP 402 não autoriza isolamento técnico.
- Referências inventadas, ferramentas desconhecidas e argumentos extras não
  alteram o estado. Nova observação invalida uma proposta anterior até que ela
  seja reapresentada.
- Falha do provedor, limite de iterações ou resposta final inválida não aplicam
  uma proposta, mesmo que ela já tivesse sido aceita pela política.

O executor tem limite de oito turnos, doze ferramentas e 45 segundos de chamadas
ao provedor. Não aceita URLs, nomes de serviços ou comandos arbitrários enviados
pelo modelo. O raciocínio interno do modelo não é solicitado ou exibido.

## Configurar na Vercel

Em **Project → Settings → Environment Variables**, cadastrar os campos abaixo
para o ambiente desejado e fazer novo deploy. Valores secretos ficam apenas
no backend; não devem ser enviados por chat nem versionados.

| Campo | Valor |
| --- | --- |
| `OBS_LLM_URL` | URL HTTPS real de uma API Chat Completions com suporte a ferramentas |
| `OBS_LLM_MODEL` | Modelo autorizado pelo provedor; os registros antigos usaram `gpt-4.1-mini` |
| `OBS_LLM_API_KEY` | Chave privada do provedor |
| `OBS_DEMO_TOKEN` | Segredo aleatório de pelo menos 32 caracteres, usado pelo apresentador |

A URL real não foi encontrada nos arquivos versionados. Se o provedor usado
for a OpenAI diretamente, sua URL base é `https://api.openai.com/v1`; isso é uma
opção de configuração, não confirmação do endpoint histórico. A chave usada
na execução antiga precisa ser recuperada com quem a configurou, ou substituída
por uma nova chave válida com acesso ao modelo.

Opcional: `OBS_EXPERIMENT_SECRET`, segredo de servidor com 32 ou mais caracteres,
**diferente do token do apresentador**, estabiliza as assinaturas ao trocar a
chave do provedor. Sem ele, a chave de assinatura é derivada criptograficamente
da chave privada do provedor. O token conhecido pelo navegador não permite
assinar um experimento ou um registro de execução.

A tela consulta `/api/agent` para saber se a configuração está presente. Isso
não garante que a chave e o modelo serão autorizados pelo provedor. A chamada
real precisa concluir antes de apresentar uma demonstração como validada.

## Roteiro para o professor

1. Abrir **Usar IA**, informar a senha e clicar em **Ativar IA**. Adicionar
   um item em Compra e carrinho.
2. Escolher **Falha no pagamento**. A análise começa após a injeção.
3. Abrir **Ver ações da IA** e conferir a ordem: injeção, observações das
   ferramentas, proposta, validação da política e ação aplicada.
4. Conferir **Última ação: Agente · política validada**. O carrinho permanece
   acessível. O backend também bloqueia o pagamento com HTTP 423 quando recebe
   o estado assinado atual do checkout isolado.
5. Solicitar aviso e clicar em **Restaurar e verificar pagamento**. A interface
   remove a falha e chama o agente. A liberação depende das duas verificações
   funcionais, da proposta e da política. Conferir aviso único e retomar a compra.
6. Repetir com recusa comercial e normalidade. Se a IA propuser isolamento sem
   evidências suficientes, mostrar a rejeição da política.
7. Exportar o JSON em **Evidências da execução** e usar **Verificar registro**
   dentro de **Ver ações da IA**. Alterar uma cópia invalida a assinatura.

A assinatura comprova integridade do registro emitido pelo servidor configurado;
não é uma auditoria independente do provedor nem uma medida de acurácia de IA.
A comparação importante é entre rótulo da intervenção (operador), observações
(ferramentas), proposta (modelo), decisão (política) e aplicação (executor).

## Validação e limites

A suíte Node executou 32 testes, todos aprovados. Os testes incluem fixtures
determinísticas de provedor **somente em testes**.
Eles verificam o protocolo, as decisões possíveis, as rejeições, o estado assinado
e o bloqueio no backend. Uma integração no navegador foi exercitada com modelo
identificado como `TEST_FIXTURE_NOT_REAL_IA`. Isso não é uma inferência real.

Não havia credenciais de LLM no ambiente desta implementação. Portanto, não foi
possível validar uma nova chamada real ao provedor nem gerar evidência de que
um modelo real escolheu corretamente as ferramentas e ações. A execução histórica
com `gpt-4.1-mini` corresponde ao núcleo antigo, não a este agente novo.

Os experimentos usam capacidades assinadas com validade de uma hora e estado
mantido pelo cliente. Não há armazenamento central, controle de concorrência
entre clientes ou revogação global de tokens anteriores. É uma demonstração
por sessão, não uma política de isolamento de pagamentos para produção.

Nenhum pagamento real é feito. Não há reparo automático, envio de mensagens
externas ou garantia financeira. Uma implantação de produção exigiria estado
persistente do lado servidor, autenticação individual, ledger e idempotência
transacional, além de avaliação semântica do modelo.
