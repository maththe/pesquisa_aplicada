// Fixed-rule baseline. It drives the same executor, tools and policy as the LLM
// agent, but a script chooses the tool calls instead of a model. The rule mirrors
// the project's "Regras" mode: any HTTP 5xx is a technical incident and isolates
// the checkout. Comparing both arms on identical infrastructure isolates the
// effect of the model's choices.
export function rulesModel() {
  let step = 0;
  let proposed = null;
  return async (messages) => {
    step++;
    const outputs = messages
      .filter((message) => message.role === "tool")
      .map((message) => JSON.parse(message.content));
    const observations = outputs.filter((item) => item.tool);
    const decisions = outputs.filter((item) => "accepted" in item);
    const task = JSON.parse(messages.find((m) => m.role === "user").content);
    const checkoutOpen = task.checkout === "open";
    const tests = observations.filter((item) => item.tool === "test_payment");
    const failures = observations.filter((item) => item.status >= 500);
    const cited = observations.map((item) => item.id).slice(-10);
    const call = (name, args) => ({
      id: `rule-${step}-${name}-${args.service || "x"}`,
      type: "function",
      function: { name, arguments: JSON.stringify(args) },
    });
    const reply = (toolCalls) => ({
      message: { role: "assistant", content: null, tool_calls: toolCalls },
      requestId: null,
      usage: null,
    });
    if (step === 1)
      return reply([
        call("probe_service", { service: "catalog" }),
        call("probe_service", { service: "cart" }),
        call("probe_service", { service: "payment" }),
        call("test_payment", {}),
      ]);
    // Releasing an isolated checkout needs a second functional check under the policy.
    if (checkoutOpen && tests.length < 2)
      return reply([call("test_payment", {})]);
    if (!proposed) {
      proposed = failures.length
        ? "isolate_checkout"
        : checkoutOpen
          ? "resume_checkout"
          : "none";
      return reply([
        call("propose_action", {
          action: proposed,
          evidence_ids: cited,
          reason: "Regra fixa: qualquer HTTP 5xx isola o checkout.",
        }),
      ]);
    }
    if (!decisions.at(-1)?.accepted && proposed !== "none") {
      proposed = "none";
      return reply([
        call("propose_action", {
          action: "none",
          evidence_ids: cited,
          reason: "Regra fixa: a política rejeitou a proposta anterior.",
        }),
      ]);
    }
    return {
      message: {
        role: "assistant",
        content: JSON.stringify({
          outcome: failures.length ? "incident" : "no_incident",
          summary: failures.length
            ? "Regra fixa: foi observada resposta HTTP 5xx."
            : "Regra fixa: nenhuma resposta HTTP 5xx observada.",
          evidence_ids: cited,
        }),
      },
      requestId: null,
      usage: null,
    };
  };
}
