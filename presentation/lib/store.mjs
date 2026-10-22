export const PRODUCTS = [
  {
    id: "headphones",
    name: "Fone Studio",
    category: "Áudio",
    price: 18990,
    icon: "headphones",
    color: "lavender",
  },
  {
    id: "keyboard",
    name: "Teclado Compact",
    category: "Workspace",
    price: 24990,
    icon: "keyboard",
    color: "peach",
  },
  {
    id: "speaker",
    name: "Caixa Pocket",
    category: "Áudio",
    price: 12990,
    icon: "speaker",
    color: "mint",
  },
];
export const fresh = () => ({
  version: 1,
  cart: [],
  scenario: "normal",
  breaker: "closed",
  incident: null,
  subscription: null,
  notices: [],
  evidence: [],
  orders: [],
  attempt: null,
  controlMode: "rules",
  agentExperiment: null,
  agentRuns: [],
  actionSource: null,
});
export function readState(storage) {
  try {
    const value = JSON.parse(storage.getItem("nexo-demo-v1"));
    if (!value || value.version !== 1) return fresh();
    if (
      !Array.isArray(value.cart) ||
      !Array.isArray(value.evidence) ||
      !Array.isArray(value.orders) ||
      !Array.isArray(value.notices) ||
      !["normal", "outage", "slow", "declined"].includes(value.scenario) ||
      !["closed", "open", "half-open"].includes(value.breaker)
    )
      return fresh();
    if (
      value.cart.some(
        (item) =>
          !PRODUCTS.some((p) => p.id === item.id) ||
          !Number.isInteger(item.quantity) ||
          item.quantity < 1 ||
          item.quantity > 20,
      )
    )
      return fresh();
    const state = { ...fresh(), ...value };
    if (state.controlMode !== "agent" || !state.agentExperiment?.token)
      state.controlMode = "rules";
    return state;
  } catch {
    return fresh();
  }
}
export class Store {
  constructor({
    state = fresh(),
    persist = () => {},
    call,
    changed = () => {},
  }) {
    this.state = state;
    this.persist = persist;
    this.call = call;
    this.changed = changed;
  }
  save() {
    this.persist(this.state);
    this.changed();
  }
  event(event, status, details) {
    const entry = {
      id: crypto.randomUUID(),
      timestamp: new Date().toISOString(),
      event,
      status,
      details,
    };
    this.state.evidence.push(entry);
    this.state.evidence = this.state.evidence.slice(-200);
    this.save();
    return entry;
  }
  total() {
    return this.state.cart.reduce(
      (sum, item) =>
        sum + PRODUCTS.find((p) => p.id === item.id).price * item.quantity,
      0,
    );
  }
  add(id) {
    if (this.state.attempt?.unknown)
      throw new Error(
        "Consulte o pagamento pendente antes de alterar o carrinho.",
      );
    if (!PRODUCTS.some((p) => p.id === id))
      throw new Error("Produto inválido.");
    const found = this.state.cart.find((item) => item.id === id);
    if (found && found.quantity >= 20)
      throw new Error("Limite de 20 unidades por produto.");
    if (found) found.quantity++;
    else this.state.cart.push({ id, quantity: 1 });
    this.state.attempt = null;
    this.event("cart_item_added", null, `${id}; itens salvos neste navegador`);
  }
  remove(id) {
    if (this.state.attempt?.unknown)
      throw new Error(
        "Consulte o pagamento pendente antes de alterar o carrinho.",
      );
    this.state.cart = this.state.cart.filter((item) => item.id !== id);
    this.state.attempt = null;
    this.event("cart_item_removed", null, id);
  }
  async request(operation, attempt = this.state.attempt) {
    const started = performance.now();
    let result;
    try {
      result = await this.call({
        operation,
        scenario:
          operation === "reconcile" ? attempt.scenario : this.state.scenario,
        attemptId: attempt?.id,
        items: attempt?.items,
      });
    } catch (error) {
      this.event(
        "payment_transport_error",
        null,
        "Não foi possível obter resposta da API. O status do serviço não foi confirmado.",
      );
      throw error;
    }
    this.event(
      `payment_${operation}`,
      result.status,
      `${result.data.outcome || result.data.status || result.data.error}; ${Math.round(performance.now() - started)} ms`,
    );
    return result;
  }
  openCircuit(source = "rules") {
    this.state.actionSource = source;
    this.state.breaker = "open";
    this.state.incident ||= crypto.randomUUID();
    this.event(
      "circuit_opened",
      null,
      source === "agent"
        ? "Isolamento aplicado após decisão do agente e validação da política."
        : "Proteção por regra técnica; novas finalizações suspensas. A IA não executou esta ação.",
    );
  }
  async scenario(scenario) {
    if (!["normal", "outage", "slow", "declined"].includes(scenario))
      throw new Error("Cenário inválido.");
    if (this.state.attempt?.unknown)
      throw new Error(
        "Reconcilie o pagamento pendente antes de trocar o cenário.",
      );
    this.state.scenario = scenario;
    this.event("experiment_scenario_changed", null, scenario);
    if (scenario === "outage") {
      let response;
      try {
        response = await this.request("probe");
      } catch (error) {
        this.openCircuit();
        throw error;
      }
      if (response.status >= 500) this.openCircuit();
      else throw new Error("A API não confirmou a falha solicitada.");
    } else if (this.state.breaker !== "closed") {
      this.state.breaker = "half-open";
      this.save();
      for (let i = 0; i < 2; i++) {
        let response;
        try {
          response = await this.request("probe");
        } catch {
          this.openCircuit();
          return false;
        }
        if (response.status !== 200 || response.data.status !== "available") {
          this.openCircuit();
          return false;
        }
      }
      this.closeCircuit();
    } else {
      const response = await this.request("probe");
      if (response.status >= 500 && scenario !== "slow") this.openCircuit();
    }
    return true;
  }
  closeCircuit(source = "rules") {
    this.state.actionSource = source;
    this.state.breaker = "closed";
    this.event(
      "circuit_closed",
      200,
      source === "agent"
        ? "Liberação aplicada após decisão do agente e validação da política."
        : "Duas sondagens funcionais confirmaram a recuperação no sandbox.",
    );
    if (
      this.state.subscription?.incident === this.state.incident &&
      !this.state.subscription.sent
    ) {
      this.state.subscription.sent = true;
      this.state.notices = this.state.notices.slice(-19);
      this.state.notices.push({
        id: crypto.randomUUID(),
        incident: this.state.incident,
        at: new Date().toISOString(),
        text: "O pagamento voltou a funcionar. Seu carrinho está salvo; você já pode retomar a compra.",
      });
      this.event(
        "recovery_notice_created",
        null,
        "Aviso interno único, solicitado pelo comprador. Nenhum e-mail enviado.",
      );
    }
    this.state.incident = null;
    this.save();
  }
  connectExperiment(payload) {
    if (
      !payload?.experiment ||
      !["closed", "open"].includes(payload.experiment.checkout) ||
      typeof payload.stateToken !== "string"
    )
      throw new Error("Experimento inválido.");
    this.state.agentExperiment = {
      ...payload.experiment,
      token: payload.stateToken,
    };
    this.state.breaker = payload.experiment.checkout;
    this.save();
  }
  injectExperiment(payload, scenario) {
    this.state.agentExperiment = {
      ...payload.experiment,
      token: payload.stateToken,
    };
    this.state.scenario = scenario;
    this.event("fault_injected", null, scenario);
    // No isolation action here. The model must investigate and propose it.
  }
  applyAgentRun(payload) {
    const current = this.state.agentExperiment;
    if (
      !current ||
      payload.run.experimentId !== current.id ||
      payload.run.revision !== current.revision
    )
      throw new Error("Execução desatualizada. Execute o agente novamente.");
    this.state.agentRuns ||= [];
    this.state.agentRuns.push({
      run: payload.run,
      signature: payload.signature,
    });
    this.state.agentRuns = this.state.agentRuns.slice(-10);
    if (payload.run.status === "completed") {
      this.state.agentExperiment = {
        ...payload.experiment,
        token: payload.stateToken,
      };
      if (payload.run.applied?.action === "isolate_checkout")
        this.openCircuit("agent");
      if (payload.run.applied?.action === "resume_checkout")
        this.closeCircuit("agent");
    }
    this.event(
      payload.run.status === "completed" ? "agent_completed" : "agent_failed",
      null,
      payload.run.id,
    );
  }
  subscribe() {
    if (!this.state.incident)
      throw new Error("Não há incidente ativo para acompanhar.");
    if (this.state.subscription?.incident === this.state.incident) return;
    this.state.subscription = {
      incident: this.state.incident,
      sent: false,
      at: new Date().toISOString(),
    };
    this.event(
      "recovery_notice_requested",
      null,
      "Consentimento para aviso dentro desta aplicação.",
    );
  }
  finish(data) {
    if (
      !this.state.orders.some((order) => order.receiptId === data.receiptId)
    ) {
      this.state.orders = this.state.orders.slice(-19);
      this.state.orders.push({
        receiptId: data.receiptId,
        total: data.total,
        at: new Date().toISOString(),
        items: data.items,
      });
    }
    this.state.cart = [];
    this.state.attempt = null;
    this.event(
      "order_confirmed",
      200,
      `${data.receiptId}; pagamento simulado, sem cobrança real`,
    );
    return data;
  }
  async checkout() {
    if (!this.state.cart.length)
      throw new Error("Adicione um produto ao carrinho.");
    if (this.state.attempt?.unknown)
      throw new Error(
        "Existe uma tentativa pendente. Consulte o resultado antes de tentar novamente.",
      );
    if (this.state.breaker !== "closed") {
      this.event(
        "checkout_blocked",
        null,
        "Circuito aberto; chamada de pagamento evitada e carrinho preservado.",
      );
      throw new Error("Pagamento indisponível. Seus itens continuam salvos.");
    }
    this.state.attempt ||= {
      id: crypto.randomUUID(),
      items: structuredClone(this.state.cart),
      scenario: this.state.scenario,
      unknown: false,
    };
    this.state.attempt.scenario = this.state.scenario;
    this.save();
    let result;
    try {
      result = await this.request("pay");
    } catch (error) {
      // Lost response: don't assume failure or create another payment.
      this.state.attempt.unknown = true;
      this.event(
        "payment_response_lost",
        null,
        "Resultado desconhecido. Nova finalização bloqueada.",
      );
      throw error;
    }
    if (result.status === 200 && result.data.outcome === "approved")
      return this.finish(result.data);
    if (result.status === 504) {
      this.state.attempt.unknown = true;
      this.openCircuit();
      throw new Error(
        "Resposta de pagamento desconhecida. Consulte a tentativa pendente antes de continuar.",
      );
    }
    if (result.status === 503) this.openCircuit();
    else this.state.attempt = null;
    this.save();
    throw new Error(result.data.error || "Pagamento não concluído.");
  }
  async reconcile() {
    if (!this.state.attempt?.unknown)
      throw new Error("Nenhum pagamento pendente.");
    const result = await this.request("reconcile");
    if (
      result.status === 402 ||
      (result.status === 503 && this.state.attempt.scenario === "outage")
    ) {
      this.state.attempt = null;
      this.save();
      throw new Error(
        "Consulta confirmou que o pagamento de teste não foi aprovado. Carrinho preservado.",
      );
    }
    if (result.status !== 200 || result.data.outcome !== "approved")
      throw new Error(
        "Resultado ainda não confirmado. Carrinho preservado; não inicie nova cobrança.",
      );
    return this.finish(result.data);
  }
}
export function rules(evidence) {
  const recent = evidence.slice(-32);
  const failures = recent.filter((item) => item.status >= 500);
  const declined = recent.filter((item) => item.status === 402);
  return {
    mode: "rules",
    outcome: failures.length
      ? "incident"
      : recent.length
        ? "no_incident"
        : "insufficient_evidence",
    summary: failures.length
      ? "Foram observadas falhas técnicas no serviço de pagamento. O circuito protege a finalização e o carrinho permanece disponível. Um timeout exige consulta da tentativa; não comprova que o pagamento falhou. A origem interna da falha não pode ser inferida só pelo HTTP."
      : declined.length
        ? "Foi observada uma recusa de pagamento (HTTP 402). Isso é diferente de indisponibilidade técnica e não deve abrir o circuito."
        : "As evidências selecionadas não mostram falha técnica de pagamento. Isso não comprova disponibilidade fora desta janela.",
    evidence_ids: (failures.length
      ? failures
      : declined.length
        ? declined
        : recent.slice(-3)
    ).map((item) => item.id),
  };
}
