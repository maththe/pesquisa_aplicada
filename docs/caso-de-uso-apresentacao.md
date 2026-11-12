# Caso de uso para apresentação — Incidente no atendimento de uma loja virtual

## História e problema

Uma loja virtual fictícia recebe contatos de clientes que não conseguem consultar
seus pedidos. A atendente tenta abrir o pedido de ID 1 e recebe uma falha. Sem os
dados do pedido e do cliente, ela não consegue concluir o atendimento.

O operador técnico verifica o Gateway e o serviço de pedidos: ambos continuam
respondendo aos testes de saúde locais. Portanto, saber que os processos estão
ativos não explica por que a operação do cliente falha.

A pergunta da investigação é: **qual dependência está impedindo a consulta do
pedido, quais evidências sustentam essa hipótese e o que deve ser verificado
antes de encerrar o incidente?**

A loja, a atendente e o contato do cliente são elementos narrativos fictícios.
A execução utiliza APIs reais em containers, dados fictícios em memória e uma
LLM real configurada pelo apresentador. O protótipo executa consulta de pedidos
e usuários; não executa pagamento, checkout ou envio de mensagens.

## Pessoas e responsabilidades

| Participante | Necessidade ou ação |
| --- | --- |
| Cliente | Consultar um pedido existente |
| Atendente, representada pelo apresentador | Reproduzir a falha na consulta e explicar o impacto no atendimento |
| Operador técnico, representado pelo apresentador | Investigar, conferir evidências e autorizar a intervenção |
| Artefato | Reunir logs e métricas, produzir hipóteses e permitir auditoria |
| Controlador do experimento | Introduzir a indisponibilidade e restaurar o serviço |

## O que acontece no sistema

```mermaid
sequenceDiagram
    participant A as Atendente / cliente HTTP
    participant G as Gateway
    participant O as Orders
    participant U as Users
    A->>G: Consultar pedido 1 + X-Request-ID
    G->>O: Buscar pedido 1
    O->>U: Buscar usuário 1
    U--xO: Conexão indisponível ou timeout
    O-->>G: Falha de dependência
    G-->>A: HTTP 503 ou 504
    Note over G,O: Health local pode responder 200
```

O experimento interrompe Users externamente. O diagnóstico recebe os sinais da
aplicação, sem receber a informação de que um container foi parado. Assim, a
hipótese esperada é indisponibilidade ou timeout de Users; a causa administrativa
da parada não pode ser deduzida como certeza a partir desses sinais.

## Perguntas que tornam a demonstração uma investigação

1. A consulta funciona antes da intervenção?
2. Uma falha no Gateway significa que o defeito está no Gateway?
3. Um healthcheck HTTP 200 garante que a consulta do pedido funciona?
4. O mesmo request ID permite seguir a falha entre Gateway e Orders?
5. O diagnóstico aponta Users e cita evidências consultáveis?
6. Depois da intervenção humana, a operação do cliente volta a funcionar?

## Roteiro de 12 a 15 minutos

| Tempo | Cena | O que mostrar | Mensagem para a banca |
| --- | --- | --- | --- |
| 0–2 min | Chamado de atendimento | A história e a pergunta da investigação | Uma falha de dependência impede uma operação de negócio |
| 2–4 min | Operação normal | Consulta do pedido, consultas de amostra e diagnóstico | Existe uma referência funcional antes do incidente |
| 4–6 min | Cliente afetado | HTTP 503/504, consultas afetadas e health local do Gateway | Processo ativo e operação funcional são condições diferentes |
| 6–9 min | Investigação | Request ID, eventos de dependência, snapshot e hipótese com IDs | O artefato reúne sinais dispersos em uma explicação verificável |
| 9–11 min | Decisão humana | Limitações, evidências originais e ação de restauração | A recomendação orienta a investigação; o operador decide a ação |
| 11–13 min | Validação | HTTP 200 após recuperação e diagnóstico da nova requisição | Encerrar o incidente exige confirmar a operação do cliente |
| 13–15 min | Valor e limites | Quadro antes/durante/depois e histórico da execução | O cenário demonstra apoio ao diagnóstico e rastreabilidade |

### Fala de abertura

> “O cliente não consegue consultar seu pedido. Os serviços de entrada e pedidos
> parecem saudáveis, mas a operação falha. Vou mostrar como o artefato reúne os
> sinais desse incidente, indica a dependência envolvida e permite conferir as
> evidências antes de uma decisão de recuperação.”

### Fala durante a investigação

> “O erro percebido está no Gateway. Seguindo a mesma requisição, encontramos a
> falha de Orders ao acessar Users. O diagnóstico cita os registros usados nessa
> hipótese. Vou abrir uma dessas evidências para conferir o que foi observado.”

### Fala de encerramento

> “A consulta voltou a funcionar após a restauração. Nesta execução, o artefato
> apoiou a localização da dependência envolvida e preservou o caminho de evidências.
> Ainda não medimos quanto tempo ele economiza em relação à investigação manual.”

## Execução guiada

Preparar o ambiente e a LLM conforme `README.md` e `docs/demonstracao.md`. Depois:

```powershell
.\.venv\Scripts\python.exe -B experiments\demonstrate.py --interactive --samples 3
```

O roteiro faz pausas antes das três etapas. Em cada uma, executa a requisição de
diagnóstico e uma amostra de consultas adicionais, registra os resultados e a
latência observada no cliente. As amostras são sequenciais: não constituem um
teste de carga. O healthcheck observado é o do Gateway; o snapshot contém os
sinais coletados para os demais serviços.

O novo relatório oferece uma comparação entre situação normal, indisponibilidade
e recuperação. Durante a pausa antes da recuperação, abra
`indisponibilidade.json` na pasta criada para a execução e consulte uma evidência:

```powershell
docker compose run --rm --no-deps diagnostics evidence ID_CITADO_NO_DIAGNOSTICO
docker compose run --rm --no-deps diagnostics run ID_DA_EXECUCAO
```

Não use IDs ilustrativos como se fossem resultados. Copie os IDs da execução.
Se houver falha do provedor ou uma hipótese inadequada, apresente o resultado
registrado e explique a limitação observada.

## Quadro de evidências e critérios de sucesso

| Afirmação apresentada | Evidência necessária | Critério |
| --- | --- | --- |
| A operação funcionava | Resposta da consulta normal | HTTP 200 |
| O atendimento foi afetado | Respostas das consultas durante a falha | HTTP 503 ou 504 e quantidade observada de consultas com falha |
| Health local não basta | Health do Gateway e consulta do pedido na mesma etapa | Health 200 e consulta com falha |
| A falha atravessa dependências | Logs correlacionados | Orders aponta Users e o erro chega ao Gateway |
| O diagnóstico é verificável | Hipótese, IDs e registros originais | Referências presentes no contexto e recuperáveis no histórico |
| A recuperação funcionou | Nova consulta e amostras após restauração | HTTP 200 |
| O caso pode ser auditado | Contextos, respostas e tentativas persistidas | Execução recuperável pelo ID |

A taxa de falha e a latência descrevem somente as consultas realizadas nesta
execução. Não extrapolar esses números para todos os clientes da loja. Não há
medição de receita, abandono de compra ou redução de tempo de atendimento.

## Comparação com a investigação manual

Mostre o mesmo incidente por duas formas: primeiro, o sintoma e registros
separados; depois, o contexto correlacionado, a hipótese e suas referências.
Essa comparação é ilustrativa. Para alegar ganho de tempo, será necessário
comparar participantes ou execuções com tarefas equivalentes e critérios
predefinidos. O tempo total do script inclui chamadas Docker e verificações de
auditoria; não é uma medida de tempo humano de diagnóstico.

## Extensão opcional — delimitar o incidente

Durante a indisponibilidade, consulte também `GET /orders/999`. Esse pedido não
existe, e Orders responde 404 antes de consultar Users. Já o pedido existente
de ID 1 depende de Users e falha com 503 ou 504.

Esse contraste ajuda a explicar que serviços ativos podem atender uma rota e
falhar em outra, conforme as dependências da operação. O 404 é uma resposta
esperada para um dado inexistente; ele não equivale à indisponibilidade da
consulta de um pedido válido.

Essa verificação é manual e não está entre as três etapas automatizadas.
Registre o status observado se a utilizar. O roteiro atual não testa a
classificação de 404 pela LLM; não atribua esse resultado ao diagnóstico.

## Extensão ao vivo — cenários com falhas injetadas

Na interface de apresentação em `http://127.0.0.1:8090`, cada botão aplica um
cenário, gera tráfego de negócio, coleta evidências e pede o diagnóstico à LLM
real. Abaixo do resultado, a tabela **“Quem identificou o problema?”** compara o
gabarito com health checks, sonda sintética e IA.

| Botão | Falha injetada | O que mostrar |
| --- | --- | --- |
| 1 · Testar tudo certo | nenhuma (controle) | a IA não inventa incidente |
| 2 · Users fora do ar | processo do Users parado | health aponta o Users; a sonda só vê o Gateway |
| 3 · Recuperar serviços | remove todas as falhas | volta ao normal sem alarme |
| 4 · Sobrecarga no Users | limite de 3 simultâneas, rajada de 12 | todos os health 200, mesmo com 9 falhas |
| 5 · Erro interno no Orders | exceção em toda consulta do Orders | a origem está no meio da cadeia, não no Users |
| 6 · Lentidão no Users | Users responde em 3 s | timeout em Orders; nenhum erro no Users |
| 7 · Falha intermitente | metade das consultas do Orders falha | padrão parcial, difícil de ver em health |
| 8 · Log malicioso | Users parado + caminho com instrução para a IA | a IA ignora a instrução e mantém o incidente |

Cada consulta recebe um identificador próprio, filho do identificador do cenário
(`overload-….01`, `overload-….02`). A falha aplicada continua ativa até o próximo
cenário; use **3 · Recuperar serviços** para voltar ao estado normal.

Cada diagnóstico leva de 40 a 60 segundos por causa do modelo. Use esse tempo para
narrar o que está sendo coletado.

### Fala sugerida

> “Agora a falha não está sempre no mesmo lugar. Neste cenário o Orders quebra e
> o Users continua saudável. Os três health checks estão verdes, então o
> monitoramento tradicional não alarma. A sonda de negócio percebe que o pedido
> falhou, mas só enxerga a entrada. O artefato coleta os logs dos três serviços,
> correlaciona a cadeia e a IA aponta o Orders, citando as evidências.”

Os limites, atrasos e erros são artificiais e só existem para a demonstração.
O erro interno aparece nos logs como uma exceção comum, sem indicação de que foi
injetado: a IA precisa inferir a origem pela propagação entre os serviços.

### Modo automático

Marque **Disparo automático pelo etcd** antes de clicar. O botão só injeta a falha e
gera tráfego; ninguém pede o diagnóstico. O coletor publica no etcd os sinais de
negócio, o gatilho compara com os limites e, ao violar, chama a IA sozinho. O painel
**Gatilho automático** mostra o limite violado e o tempo até o disparo.

> “Agora eu não peço nada. Só quebro o Orders e deixo o tráfego correr. Em poucos
> segundos a taxa de erro no snapshot do etcd passa do limite, o gatilho dispara e a
> IA investiga sozinha. Repare que o alerta acusa Gateway e Orders ao mesmo tempo;
> quem separa a causa do sintoma é o diagnóstico.”

No controle (botão 1), o gatilho não dispara e nenhuma chamada à IA é feita: bom
para mostrar que o artefato não gasta nem alarma à toa.

## Avaliação com gabarito

`docs/evidencias/avaliacao-20261112T013517Z-fd1887/relatorio.md` registra uma
rodada completa dos oito cenários (mais um controle repetido), com LLM real:

| Método | Detecção correta | Localização correta | Falsos positivos |
| --- | --- | --- | --- |
| Health checks | 5/9 | 2/6 | 0/3 |
| Sonda sintética | 9/9 | 0/6 | 0/3 |
| IA (artefato) | 9/9 | 6/6 | 0/3 |

É uma rodada por cenário: indica viabilidade e tendência, não acurácia geral.
O método e as ameaças à validade estão em `docs/avaliacao.md`.

## Evidência histórica disponível

A execução de 24/09/2026, registrada em
`docs/evidencias/20260924T221853Z-40eb62/`, utilizou LLM real e apresentou:

| Situação | HTTP | Resultado do diagnóstico |
| --- | --- | --- |
| Normal | 200 | `no_incident` |
| Users indisponível | 504 | `incident`, com hipótese referente a Users |
| Recuperação | 200 | `no_incident` |

Esses arquivos permitem uma apresentação baseada em evidências existentes caso
a execução ao vivo não esteja disponível. Eles não contêm as novas medições de
amostras e latências: esses resultados dependem de uma nova execução do roteiro.

## Perguntas prováveis da banca

**“O artefato corrige o código?”** Apoia a investigação de falhas em execução.
A correção ou restauração depende da análise e da decisão humanas.

**“Como sabemos que a IA não recebeu a resposta?”** O registro da intervenção
fica em `controle-experimental.json`, separado dos logs e snapshots fornecidos
ao diagnóstico. O contexto enviado pode ser inspecionado em `run.context`.

**“Ela descobriu por que Users parou?”** Identificou os sinais de
indisponibilidade e seu impacto. Determinar a causa da parada exige outras
evidências.

**“Isso já prova eficiência ou acurácia geral?”** Não. A avaliação com gabarito
cobre cinco tipos de falha em dois serviços e compara com health checks e sonda
sintética, mas em ambiente controlado e com poucas repetições. Indica tendência,
não significância estatística.

**“A IA não acerta só porque o problema é sempre no Users?”** Não é sempre: dois
cenários têm origem no Orders, e os controles verificam que ela não alarma à toa.

**“O que aciona a IA?”** Pode ser o operador (botões no modo manual) ou o gatilho
automático: limites de taxa de erro, latência p95 e disponibilidade guardados no etcd,
comparados a cada snapshot. Um diagnóstico por incidente, com intervalo mínimo, para
não gastar à toa.

**“E se alguém escrever instruções nos logs?”** O cenário 8 coloca uma instrução
maliciosa no caminho de uma requisição. O prompt trata logs como dados não
confiáveis, e a IA manteve o diagnóstico de incidente no Users.
