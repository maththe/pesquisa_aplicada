import { Store, fresh, readState, PRODUCTS, rules } from "./lib/store.mjs";
const $ = (selector) => document.querySelector(selector);
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const money = (cents) =>
  new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(
    cents / 100,
  );
const time = (date) =>
  new Date(date).toLocaleTimeString("pt-BR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
let actionController = null;
let busy = false,
  diagnosis = null,
  testReport = null,
  storageAvailable = true,
  timer;
let agentConfigured = false,
  agentVerified = null;
const icons = {
  headphones:
    '<path d="M28 83V60a32 32 0 0 1 64 0v23" fill="none" stroke="#665f83" stroke-width="12"/><rect x="20" y="60" width="20" height="38" rx="8" fill="#9186b1"/><rect x="80" y="60" width="20" height="38" rx="8" fill="#9186b1"/><path d="M30 41a34 34 0 0 1 58-2" fill="none" stroke="#c0b7da" stroke-width="4"/>',
  keyboard:
    '<rect x="6" y="35" width="110" height="56" rx="7" fill="#b79d80"/><rect x="9" y="32" width="104" height="52" rx="6" fill="#e1ccb2"/><path d="M18 43h87M18 55h87M18 67h87M27 38v33M42 38v33M57 38v22M72 38v22M87 38v33M102 38v33" stroke="#af967b" stroke-width="6"/><path d="M44 72h35" stroke="#f9efdc" stroke-width="7"/>',
  speaker:
    '<rect x="31" y="17" width="58" height="88" rx="18" fill="#456b56"/><rect x="35" y="20" width="50" height="80" rx="15" fill="#87a58c"/><circle cx="60" cy="60" r="20" fill="#52785f"/><circle cx="60" cy="60" r="14" fill="#6d9277"/><path d="M48 30h24" stroke="#d0e2cb" stroke-width="4" stroke-linecap="round"/>',
};
$("#product-list").innerHTML = PRODUCTS.map(
  (p) =>
    `<article class="product"><div class="product-art ${p.color}"><svg viewBox="0 0 120 120" aria-hidden="true">${icons[p.icon]}</svg></div><span class="product-category">${p.category}</span><h3>${p.name}</h3><div class="product-bottom"><strong>${money(p.price)}</strong><button class="add-btn" data-add="${p.id}" aria-label="Adicionar ${p.name} ao carrinho">+</button></div></article>`,
).join("");
function toast(message) {
  clearTimeout(timer);
  $("#toast").textContent = message;
  $("#toast").hidden = false;
  timer = setTimeout(() => ($("#toast").hidden = true), 6500);
}
async function call(body, useExperiment = true) {
  const headers = { "Content-Type": "application/json" };
  if (
    useExperiment &&
    store.state.controlMode === "agent" &&
    store.state.agentExperiment?.token
  )
    headers["X-Experiment-State"] = store.state.agentExperiment.token;
  const response = await fetch("/api/payments", {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    cache: "no-store",
    signal: requestSignal(12000),
  });
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error(
      "A API não respondeu em JSON. Confira se este deploy contém as funções /api.",
    );
  }
  return { status: response.status, data };
}
let saved;
try {
  saved = readState(localStorage);
} catch {
  saved = fresh();
  storageAvailable = false;
}
// Access password is intentionally not persisted; activate the agent explicitly after reload.
saved.controlMode = "rules";
const store = new Store({
  state: saved,
  call,
  persist: (state) => {
    try {
      localStorage.setItem("nexo-demo-v1", JSON.stringify(state));
    } catch {
      storageAvailable = false;
    }
  },
  changed: () => render(),
});
let storageWarningShown = false;
function render() {
  const s = store.state,
    blocked = s.breaker !== "closed",
    unknown = s.attempt?.unknown;
  const lastRun = s.agentRuns?.at(-1)?.run;
  const currentRun =
    s.controlMode === "agent" &&
    lastRun &&
    lastRun.experimentId === s.agentExperiment?.id &&
    s.agentExperiment.revision === lastRun.revision + (lastRun.applied ? 1 : 0)
      ? lastRun
      : null;
  const agentPayment = currentRun?.observations
    .filter((item) => item.service === "payment")
    .at(-1);

  $("#cart-count").textContent = s.cart.reduce((n, i) => n + i.quantity, 0);
  $("#cart-total").textContent = money(store.total());
  $("#cart-items").innerHTML = s.cart.length
    ? s.cart
        .map((item) => {
          const p = PRODUCTS.find((p) => p.id === item.id);
          return `<div class="cart-item"><div><h4>${p.name}</h4><small>${item.quantity} un. × ${money(p.price)}</small></div><button class="remove" data-remove="${p.id}" aria-label="Remover ${p.name}">×</button></div>`;
        })
        .join("")
    : '<div class="empty-cart"><span>⌑</span>Carrinho vazio.</div>';
  $("#checkout").disabled = busy || !s.cart.length || blocked || unknown;
  $("#checkout").innerHTML = unknown
    ? "Pagamento pendente de consulta"
    : blocked
      ? "Pagamento temporariamente suspenso"
      : "Finalizar compra <span>→</span>";
  $("#reconcile").hidden = !unknown;
  $("#reconcile").disabled = busy;
  $("#payment-notice").hidden = !blocked && !unknown;
  $("#payment-notice").innerHTML = unknown
    ? "<p><strong>Não tente pagar novamente.</strong> A resposta é desconhecida. Consulte a tentativa pendente; seus itens estão preservados.</p>"
    : `<p>O processamento de pagamentos está temporariamente indisponível. Seus itens continuam salvos. Deseja receber um aviso quando voltar?</p>${s.subscription?.incident === s.incident ? "<strong>Aviso solicitado. Acompanhe a recuperação nesta página.</strong>" : '<button id="subscribe">Quero receber um aviso</button>'}`;
  $("#payment-status").textContent = unknown
    ? "Resultado desconhecido"
    : blocked
      ? "Indisponível"
      : s.scenario === "declined"
        ? "Ativo · recusa de teste"
        : s.scenario === "slow"
          ? "Timeout preparado"
          : s.evidence.some(
                (e) => e.event === "payment_probe" || e.event === "payment_pay",
              )
            ? "Disponível"
            : "Não verificado";
  if (!blocked && !unknown && s.controlMode === "agent")
    $("#payment-status").textContent = agentPayment
      ? agentPayment.status >= 500
        ? "Falha observada"
        : agentPayment.status === 402
          ? "Recusa · serviço ativo"
          : "Disponível"
      : "Não verificado";
  $("#payment-dot").className =
    "status-dot " +
    (blocked || unknown || agentPayment?.status >= 500 ? "bad" : "ok");
  $("#circuit-status").textContent = {
    open: "Aberto · compra protegida",
    "half-open": "Validando recuperação",
    closed: "Fechado · compra liberada",
  }[s.breaker];
  $("#circuit-dot").className = "status-dot " + (blocked ? "bad" : "ok");
  $("#notifications").innerHTML = s.notices
    .slice(-3)
    .map(
      (n) =>
        `<div class="notification"><span>✓</span><div>${esc(n.text)}<small>Aviso de recuperação · ${time(n.at)}</small></div></div>`,
    )
    .join("");
  $("#order-result").innerHTML = s.orders.length
    ? `<div class="order-success"><b>Compra confirmada ✓</b><br>${esc(s.orders.at(-1).receiptId)}<br>${money(s.orders.at(-1).total)}</div>`
    : "";
  $("#event-count").textContent = `${s.evidence.length} eventos`;
  $("#metric-evidence").textContent = `${s.evidence.length} eventos`;
  const lastHttp =
    s.controlMode === "agent"
      ? agentPayment
      : s.evidence.findLast((event) => event.status != null);
  const lastAction = s.evidence.findLast((e) =>
    ["circuit_opened", "circuit_closed"].includes(e.event),
  );
  let incident = [
    "Escolha um cenário",
    "O resultado da execução aparece aqui.",
    "Aguardando teste",
  ];
  if (lastHttp)
    incident = [
      "Pagamento respondeu",
      `Última resposta: HTTP ${lastHttp.status}.`,
      "Resposta recebida",
    ];
  if (s.scenario === "slow" && !unknown)
    incident = [
      "Resposta perdida selecionada",
      "Execute uma compra para provocar o timeout e verificar a consulta da tentativa original.",
      "Pronto para testar",
    ];
  if (s.scenario === "declined" && !blocked)
    incident = [
      "Recusa de pagamento",
      "A recusa é uma resposta de negócio. Quando a compra retorna HTTP 402, o carrinho é mantido e o serviço continua liberado.",
      "Sem isolamento técnico",
    ];
  if (blocked)
    incident = [
      "Pagamento isolado",
      "O checkout foi suspenso após a falha. O catálogo continua disponível e os itens permanecem no carrinho.",
      "Compra suspensa",
    ];
  if (unknown)
    incident = [
      "Pagamento sem confirmação",
      "A resposta da compra se perdeu. Uma nova tentativa fica bloqueada até consultar o resultado pelo mesmo identificador, evitando repetir a compra.",
      "Consulta necessária",
    ];
  if (
    !blocked &&
    !unknown &&
    s.scenario === "normal" &&
    lastAction?.event === "circuit_closed"
  )
    incident = [
      "Conexão restabelecida no teste",
      "O cenário de falha foi removido. Duas verificações confirmaram o pagamento disponível antes de liberar o checkout; o carrinho foi preservado.",
      "Checkout liberado",
    ];
  $("#incident-explanation").innerHTML =
    `<div><span class="incident-badge">${esc(incident[2])}</span><h3>${esc(incident[0])}</h3><p>${esc(incident[1])}</p></div><div class="incident-proof"><b>${lastHttp ? `HTTP ${esc(lastHttp.status)}` : "—"}</b><span>${s.controlMode === "agent" ? "Controle: agente IA" : "Controle: regras automáticas"}</span></div>`;
  $("#metric-http").textContent = lastHttp
    ? `HTTP ${lastHttp.status}`
    : "Não verificada";
  $("#metric-isolation").textContent = unknown
    ? "Consulta pendente"
    : blocked
      ? "Falha contida"
      : "Liberado";
  $("#payment-component").className =
    "component" +
    (blocked || unknown ? " isolated" : lastHttp ? " available" : "");
  $("#isolation-payment-status").textContent = unknown
    ? "Resultado desconhecido"
    : blocked
      ? "Finalização isolada"
      : lastHttp
        ? "Finalização liberada"
        : "Não verificado";
  if (testReport) {
    const passed = testReport.results.filter((result) => result.passed).length;
    $("#metric-tests").textContent =
      `${passed}/${testReport.results.length} aprovados`;
  }

  $("#timeline").innerHTML = s.evidence.length
    ? s.evidence
        .slice()
        .reverse()
        .map(
          (e) =>
            `<article class="event" id="event-${esc(e.id)}"><time>${time(e.timestamp)}</time><div><b>${esc(e.event)}</b><p>${esc(e.details)}</p><code>${esc(e.id)}</code></div>${e.status ? `<span class="http ${e.status >= 400 ? "bad" : ""}">${esc(e.status)}</span>` : ""}</article>`,
        )
        .join("")
    : '<p class="empty-cart">As evidências da sua sessão aparecerão aqui.</p>';
  document.querySelectorAll("[data-scenario]").forEach((button) => {
    button.classList.toggle("active", button.dataset.scenario === s.scenario);
    button.disabled = busy || unknown;
    button.setAttribute("aria-pressed", button.dataset.scenario === s.scenario);
  });
  document
    .querySelectorAll("[data-add],[data-remove]")
    .forEach((button) => (button.disabled = busy || unknown));
  for (const id of ["recover", "analyze", "run-tests"])
    $("#" + id).disabled = busy || (id === "recover" && unknown);
  $("#export").disabled = busy;
  const agentMode = s.controlMode === "agent";
  $("#control-mode option[value=agent]").disabled = !agentConfigured;
  $("#analyze").hidden = agentMode;
  if (!diagnosis)
    $("#diagnosis-mode").textContent = agentMode
      ? "Sem execução"
      : "Por regras";
  $("#control-mode").value = agentMode ? "agent" : "rules";
  $("#control-mode").disabled = busy;
  $("#llm-token").disabled = busy;
  $("#connect-agent").disabled = busy || !agentConfigured;
  $("#connect-agent").textContent =
    busy && !agentMode ? "Conectando…" : agentMode ? "Reconectar" : "Ativar IA";
  $("#disconnect-agent").hidden = !agentMode;
  $("#disconnect-agent").disabled = busy;
  $("#run-agent").hidden = !agentMode;
  $("#execution-status").hidden = !busy;
  $("#run-agent").disabled =
    busy || !agentMode || !agentConfigured || !s.agentExperiment;

  $("#action-source").textContent =
    s.actionSource === "agent"
      ? "Agente · política validada"
      : s.actionSource === "rules"
        ? "Regras"
        : "—";
  renderAgentTrace();

  if (diagnosis) {
    $("#diagnosis-mode").textContent =
      diagnosis.mode === "llm"
        ? `LLM real · ${diagnosis.model}`
        : "Por regras · sem IA";
    $("#diagnosis-summary").hidden = false;
    $("#diagnosis-summary").textContent = diagnosis.summary;
    $("#diagnosis-refs").innerHTML =
      `<div class="refs">${diagnosis.evidence_ids.map((id) => `<a class="ref" href="#event-${esc(id)}" title="${esc(id)}">${esc(id.slice(0, 8))} ↗</a>`).join("")}</div>`;
  }
  if (!storageAvailable && !storageWarningShown) {
    storageWarningShown = true;
    toast("Não foi possível salvar o carrinho.");
  }
}
function requestSignal(ms) {
  return actionController
    ? AbortSignal.any([actionController.signal, AbortSignal.timeout(ms)])
    : AbortSignal.timeout(ms);
}
function stage(message) {
  $("#execution-label").textContent = message;
}
async function action(fn) {
  if (busy) return;
  busy = true;
  actionController = new AbortController();
  const timeout = setTimeout(
    () =>
      actionController?.abort(new DOMException("Tempo limite", "TimeoutError")),
    60000,
  );
  $("#execution-error").hidden = true;
  stage("Executando…");
  render();
  try {
    await fn();
  } catch (error) {
    const message =
      error.name === "AbortError"
        ? "Execução cancelada. Você já pode tentar novamente."
        : error.name === "TimeoutError"
          ? "A resposta demorou demais. Tente novamente."
          : error.message;
    if ($("#test-results").dataset.running === "true") {
      $("#test-results").dataset.running = "false";
      $("#test-results").innerHTML =
        '<div class="test-report"><h3>Execução interrompida</h3></div>';
    }
    $("#execution-error").textContent = message;
    $("#execution-error").hidden = false;
    toast(message);
  } finally {
    clearTimeout(timeout);
    actionController = null;
    busy = false;
    render();
  }
}
$("#cancel-execution").addEventListener("click", () =>
  actionController?.abort(),
);
$("#product-list").addEventListener("click", (e) => {
  const b = e.target.closest("[data-add]");
  if (b)
    action(() => {
      store.add(b.dataset.add);
      toast(
        store.state.breaker === "closed"
          ? "Item adicionado ao carrinho."
          : "Item adicionado. O pagamento está indisponível, mas seu carrinho está salvo.",
      );
    });
});
$("#cart-items").addEventListener("click", (e) => {
  const b = e.target.closest("[data-remove]");
  if (b) action(() => store.remove(b.dataset.remove));
});
$("#payment-notice").addEventListener("click", (e) => {
  if (e.target.closest("#subscribe"))
    action(() => {
      store.subscribe();
      toast(
        "Combinado. Você receberá um aviso aqui quando a recuperação for confirmada.",
      );
    });
});
$("#checkout").addEventListener("click", () =>
  action(async () => {
    await store.checkout();
    toast("Compra confirmada.");
  }),
);
$("#reconcile").addEventListener("click", () =>
  action(async () => {
    await store.reconcile();
    toast(
      "Resultado consultado: pagamento de teste confirmado, sem criar outra tentativa.",
    );
  }),
);
document.querySelectorAll("[data-scenario]").forEach((b) =>
  b.addEventListener("click", () =>
    action(async () => {
      if (store.state.controlMode === "agent") {
        const data = await agentRequest("/api/experiment", {
          operation: "inject",
          scenario: b.dataset.scenario,
        });
        store.injectExperiment(data, b.dataset.scenario);
        await executeAgent();
      } else {
        await store.scenario(b.dataset.scenario);
        diagnosis = rules(store.state.evidence);
      }
    }),
  ),
);
$("#recover").addEventListener("click", () =>
  action(async () => {
    if (store.state.controlMode === "agent") {
      const data = await agentRequest("/api/experiment", {
        operation: "inject",
        scenario: "normal",
      });
      store.injectExperiment(data, "normal");
      await executeAgent();
    } else {
      if (await store.scenario("normal")) toast("Pagamento restaurado.");
      diagnosis = rules(store.state.evidence);
    }
  }),
);
async function agentRequest(path, body) {
  const token = $("#llm-token").value.trim();
  if (!token)
    throw new Error("Digite a senha OBS_DEMO_TOKEN para ativar a IA.");
  if (token.startsWith("sk-"))
    throw new Error(
      "Este campo usa OBS_DEMO_TOKEN. A chave da OpenAI fica somente na Vercel.",
    );
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${$("#llm-token").value.trim()}`,
      ...(store.state.agentExperiment?.token
        ? { "X-Experiment-State": store.state.agentExperiment.token }
        : {}),
    },
    body: JSON.stringify(body),
    signal: requestSignal(body.operation === "run" ? 50000 : 8000),
  });
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error("A API não respondeu. Tente novamente após o deploy.");
  }
  if (response.status === 401 || response.status === 403)
    throw new Error("Senha incorreta. Use o valor de OBS_DEMO_TOKEN.");
  if (!response.ok && !data.run)
    throw new Error(data.error || "Agente indisponível.");
  return data;
}
function renderAgentTrace() {
  const entry = store.state.agentRuns?.at(-1);
  $("#verify-agent").hidden = !entry;
  if (!entry) {
    $("#agent-run-id").textContent = "";
    $("#agent-trace").innerHTML = "";
    return;
  }
  $("#agent-run-id").textContent =
    `${entry.run.model} · ${entry.run.id}${agentVerified === true ? " · assinatura válida" : agentVerified === false ? " · assinatura inválida" : ""}`;
  const labels = {
    model_response: "Modelo",
    tool_call: "Ferramenta",
    tool_result: "Resultado",
    action_proposed: "Proposta do agente",
    policy_decision: "Política",
    diagnosis: "Diagnóstico",
    action_applied: "Ação aplicada",
    no_action: "Sem alteração",
    run_failed: "Falha na execução",
  };
  $("#agent-trace").innerHTML = entry.run.trace
    .map((step) => {
      let detail;
      if (step.type === "model_response")
        detail =
          step.toolCalls.map((call) => call.name).join(", ") ||
          "Resposta final";
      else if (step.type === "tool_call")
        detail = `${step.name} ${JSON.stringify(step.args)}`;
      else if (step.type === "tool_result")
        detail = `${step.service} · ${step.status} · ${JSON.stringify(step.result)}`;
      else if (step.type === "action_proposed")
        detail = `${step.action} · ${step.reason}`;
      else if (step.type === "policy_decision")
        detail = `${step.accepted ? "Aceita" : "Rejeitada"} · ${step.reason}`;
      else if (step.type === "diagnosis") detail = step.summary;
      else if (step.type === "action_applied")
        detail = `${step.action} · ${step.before} → ${step.after}`;
      else detail = step.error || "Nenhuma ação aplicada";
      return `<li id="event-${esc(step.id)}" class="agent-step ${step.type === "action_applied" ? "applied" : ""}"><b>${esc(labels[step.type] || step.type)}</b><span>${esc(detail)}</span>${step.providerRequestId ? `<code>${esc(step.providerRequestId)}</code>` : ""}${step.id ? `<code>${esc(step.id)}</code>` : ""}</li>`;
    })
    .join("");
}
$("#control-mode").addEventListener("change", () => {
  store.state.controlMode = $("#control-mode").value;
  store.save();
});
$("#connect-agent").addEventListener("click", () =>
  action(async () => {
    if (store.state.attempt?.unknown)
      throw new Error(
        "Consulte o pagamento pendente antes de conectar outro experimento.",
      );
    stage("Conectando à IA…");
    store.connectExperiment(
      await agentRequest("/api/experiment", { operation: "create" }),
    );
    store.state.controlMode = "agent";
    store.event("experiment_connected", null, store.state.agentExperiment.id);
    $("#agent-feedback").textContent = "IA ativada. Escolha um cenário acima.";
    $("#agent-status").textContent = "Ativada";
    toast("IA ativada. Escolha um cenário.");
  }),
);
async function executeAgent() {
  stage("IA verificando os serviços…");
  $("#agent-status").textContent = "Analisando…";
  $("#agent-feedback").textContent = "Análise em andamento…";
  try {
    const data = await agentRequest("/api/agent", {
      operation: "run",
      pendingPayment: Boolean(store.state.attempt?.unknown),
    });
    store.applyAgentRun(data);
    agentVerified = null;
    if (data.run.status !== "completed")
      throw new Error(
        "A IA não concluiu a análise. Nenhuma ação foi aplicada. Verifique a chave e o saldo da API.",
      );
    diagnosis = { ...data.run.diagnosis, mode: "llm", model: data.run.model };
    $("#agent-status").textContent = "Concluído";
    $("#agent-feedback").textContent = data.run.diagnosis.summary;
  } catch (error) {
    $("#agent-status").textContent = "Não concluído";
    $("#agent-feedback").textContent = "Análise interrompida. Tente novamente.";
    throw error;
  }
}
$("#run-agent").addEventListener("click", () => action(executeAgent));
$("#disconnect-agent").addEventListener("click", () => {
  if (busy) return;
  store.state.controlMode = "rules";
  store.save();
  $("#agent-feedback").textContent =
    "IA desativada. Testes por regras disponíveis.";
  $("#agent-status").textContent = "Disponível";
});
$("#verify-agent").addEventListener("click", () =>
  action(async () => {
    const entry = store.state.agentRuns.at(-1);
    const result = await agentRequest("/api/agent", {
      operation: "verify",
      run: entry.run,
      signature: entry.signature,
    });
    agentVerified = result.valid;
  }),
);
fetch("/api/agent", { cache: "no-store", signal: AbortSignal.timeout(6000) })
  .then((response) => {
    if (!response.ok) throw new Error("Configuração indisponível");
    return response.json();
  })
  .then((data) => {
    agentConfigured = Boolean(data.configured);
    if (!agentConfigured && store.state.controlMode === "agent") {
      store.state.controlMode = "rules";
      store.save();
    }
    $("#agent-status").textContent = agentConfigured
      ? data.model
      : "Não configurada";
    $("#agent-feedback").textContent = agentConfigured
      ? "Digite a senha OBS_DEMO_TOKEN e clique em Ativar IA."
      : "IA não configurada na Vercel. Os testes estão disponíveis acima.";
    render();
  })
  .catch(() => {
    $("#agent-status").textContent = "Indisponível";
    $("#agent-feedback").textContent =
      "IA indisponível. Os testes continuam disponíveis acima.";
    store.state.controlMode = "rules";
    store.save();
  });
$("#analyze").addEventListener("click", () =>
  action(async () => {
    const evidence = store.state.evidence.slice(-32),
      token = $("#llm-token").value.trim();
    if (!token) {
      diagnosis = rules(evidence);
      toast("Análise por regras concluída. Nenhuma LLM foi consultada.");
      return;
    }
    try {
      const response = await fetch("/api/diagnose", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ evidence }),
        signal: requestSignal(25000),
      });
      const data = await response.json();
      if (!response.ok)
        throw new Error(data.error || "Falha ao consultar a LLM.");
      diagnosis = data;
      store.event(
        "llm_diagnosis_received",
        200,
        `Modelo: ${data.model}; análise sem execução de ações`,
      );
      toast("Diagnóstico da LLM recebido e referências validadas.");
    } catch (error) {
      diagnosis = rules(evidence);
      toast(`${error.message} Exibindo análise por regras, sem IA.`);
    }
  }),
);
export async function evaluate(api = (body) => call(body, false)) {
  const results = [],
    evidence = [];
  const check = (value, message) => {
    if (!value) throw new Error(message);
  };
  const explanations = [
    [
      "Compra aprovada",
      "Nenhuma falha foi injetada.",
      "A API confirmou o total e a compra esvaziou o carrinho.",
    ],
    [
      "Serviço de pagamento indisponível",
      "A compra recebeu HTTP 503.",
      "A tentativa falhou sem remover o produto do carrinho.",
    ],
    [
      "Falha contida no checkout",
      "O pagamento ficou indisponível e o circuito abriu.",
      "A próxima compra foi bloqueada antes de uma nova chamada ao pagamento.",
    ],
    [
      "Carrinho restaurado",
      "O estado foi salvo e carregado novamente.",
      "O teclado e sua quantidade permaneceram no carrinho.",
    ],
    [
      "Pagamento recuperado",
      "O teste retirou a falha de pagamento.",
      "Duas sondagens confirmaram disponibilidade. O circuito fechou, o carrinho foi mantido e um único aviso foi criado.",
    ],
    [
      "Recusa sem derrubar o serviço",
      "A compra recebeu HTTP 402.",
      "O circuito permaneceu fechado e o produto continuou no carrinho.",
    ],
    [
      "Resposta perdida e conciliada",
      "A compra ficou sem confirmação e uma segunda tentativa foi bloqueada.",
      "A consulta usou o mesmo identificador e confirmou uma única compra.",
    ],
    [
      "Comprovante consistente",
      "Duas chamadas usaram a mesma chave de tentativa.",
      "As duas respostas HTTP 200 devolveram o mesmo comprovante no sandbox.",
    ],
  ];
  async function test(name, fn) {
    if (actionController?.signal.aborted) throw actionController.signal.reason;
    stage(`Teste ${results.length + 1}/8 · ${name}`);
    const start = performance.now();
    const offset = evidence.length;
    const [title, problem, outcome] = explanations[results.length];
    try {
      await fn();
      results.push({
        name,
        title,
        problem,
        outcome,
        observations: evidence.slice(offset),
        passed: true,
        durationMs: Math.round(performance.now() - start),
      });
    } catch (error) {
      results.push({
        name,
        title,
        problem,
        outcome: "A verificação falhou. A recuperação não foi comprovada.",
        observations: evidence.slice(offset),
        passed: false,
        error: error.message,
      });
    }
  }
  const make = () => new Store({ call: api });
  await test("Compra normal retorna HTTP 200 e comprovante", async () => {
    const s = make();
    s.add("headphones");
    const r = await s.checkout();
    check(
      r.total === 18990 && !s.state.cart.length,
      "Total ou conclusão incorretos",
    );
    evidence.push(...s.state.evidence);
  });
  await test("Falha técnica retorna HTTP 503 sem perder o carrinho", async () => {
    const s = make();
    s.add("keyboard");
    s.state.scenario = "outage";
    try {
      await s.checkout();
    } catch {}
    check(
      s.state.evidence.some((e) => e.status === 503) &&
        s.state.cart.length === 1,
      "Falha HTTP ou preservação não comprovadas",
    );
    evidence.push(...s.state.evidence);
  });
  await test("Circuito aberto evita uma nova chamada de pagamento", async () => {
    const s = make();
    s.add("speaker");
    await s.scenario("outage");
    const count = s.state.evidence.filter(
      (e) => e.event === "payment_pay",
    ).length;
    try {
      await s.checkout();
    } catch {}
    check(
      s.state.evidence.some((e) => e.event === "checkout_blocked") &&
        count ===
          s.state.evidence.filter((e) => e.event === "payment_pay").length,
      "Checkout não foi protegido",
    );
    evidence.push(...s.state.evidence);
  });
  await test("Carrinho sobrevive à restauração do estado salvo", async () => {
    const s = make();
    s.add("keyboard");
    const restored = readState({ getItem: () => JSON.stringify(s.state) });
    check(
      restored.cart[0].quantity === 1 && restored.cart[0].id === "keyboard",
      "Carrinho não restaurado",
    );
  });
  await test("Duas sondagens de recuperação e um único aviso", async () => {
    const s = make();
    s.add("speaker");
    await s.scenario("outage");
    s.subscribe();
    const before = s.state.evidence.length;
    await s.scenario("normal");
    await s.scenario("normal");
    check(
      s.state.notices.length === 1 &&
        s.state.breaker === "closed" &&
        s.state.cart.length === 1 &&
        s.state.evidence
          .slice(before)
          .filter((e) => e.event === "payment_probe" && e.status === 200)
          .length >= 2,
      "Recuperação ou aviso incorretos",
    );
    evidence.push(...s.state.evidence);
  });
  await test("Recusa HTTP 402 mantém o circuito fechado", async () => {
    const s = make();
    s.add("headphones");
    await s.scenario("declined");
    try {
      await s.checkout();
    } catch {}
    check(
      s.state.breaker === "closed" &&
        s.state.evidence.some((e) => e.status === 402) &&
        s.state.cart.length === 1,
      "Recusa confundida com falha técnica",
    );
    evidence.push(...s.state.evidence);
  });
  await test("Timeout bloqueia nova tentativa até reconciliação", async () => {
    const s = make();
    s.add("keyboard");
    await s.scenario("slow");
    try {
      await s.checkout();
    } catch {}
    const id = s.state.attempt.id;
    try {
      await s.checkout();
    } catch {}
    check(
      s.state.attempt.unknown &&
        s.state.evidence.filter((e) => e.event === "payment_pay").length === 1,
      "Nova tentativa indevida",
    );
    const r = await s.reconcile();
    check(
      r.attemptId === id && s.state.orders.length === 1 && !s.state.cart.length,
      "Reconciliação não comprovada",
    );
    evidence.push(...s.state.evidence);
  });
  await test("Mesma chave produz o mesmo comprovante de teste", async () => {
    const body = {
      operation: "pay",
      scenario: "normal",
      attemptId: crypto.randomUUID(),
      items: [{ id: "speaker", quantity: 1 }],
    };
    const a = await api(body),
      b = await api(body);
    check(
      a.status === 200 &&
        b.status === 200 &&
        a.data.receiptId === b.data.receiptId,
      "Comprovantes divergiram",
    );
  });
  return {
    executedAt: new Date().toISOString(),
    scope:
      "Avaliação funcional do sandbox; não mede acurácia de IA, pagamentos reais ou durabilidade de transações.",
    results,
    evidence,
  };
}
$("#run-tests").addEventListener("click", () =>
  action(async () => {
    $("#test-results").hidden = false;
    $("#test-results").innerHTML =
      '<div class="test-report"><h3>Executando avaliação pela API…</h3></div>';
    $("#test-results").dataset.running = "true";
    testReport = await evaluate();
    $("#test-results").dataset.running = "false";
    const passed = testReport.results.filter((r) => r.passed).length;
    $("#test-results").innerHTML =
      `<div class="test-report"><h3>${passed}/${testReport.results.length} verificações aprovadas</h3><div class="test-cards">${testReport.results.map((r, i) => `<article class="test-card ${r.passed ? "" : "fail"}"><header><span>TESTE ${String(i + 1).padStart(2, "0")}</span><b>${r.passed ? "✓ Aprovado" : "✕ Falhou"}</b></header><h4>${esc(r.title)}</h4><dl><dt>O que aconteceu</dt><dd>${esc(r.problem)}</dd><dt>${r.passed ? "Resultado confirmado" : "Resultado"}</dt><dd>${esc(r.outcome)}</dd></dl>${r.error ? `<p class="test-error">${esc(r.error)}</p>` : ""}<footer>${r.durationMs ?? "—"} ms${r.observations?.length ? ` · ${r.observations.length} eventos registrados` : ""}</footer>${r.observations?.length ? `<details><summary>Ver evidências</summary>${r.observations.map((e) => `<div class="test-observation"><code>${esc(e.event)}${e.status ? ` · HTTP ${esc(e.status)}` : ""}</code><p>${esc(e.details || "")}</p></div>`).join("")}</details>` : ""}</article>`).join("")}</div></div>`;
    toast("Avaliação concluída. Confira os resultados observados.");
  }),
);
$("#export").addEventListener("click", () => {
  const report = {
    artifact: "Nexo · Pesquisa Aplicada",
    version: "3.0.0",
    exportedAt: new Date().toISOString(),
    scope:
      "Sandbox serverless, carrinho e evidências locais neste navegador. Nenhuma cobrança real, envio externo ou reparo por IA.",
    state: {
      ...store.state,
      agentExperiment: store.state.agentExperiment
        ? { ...store.state.agentExperiment, token: undefined }
        : null,
    },
    diagnosis,
    evaluation: testReport,
  };
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = `nexo-evidencias-${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
render();
