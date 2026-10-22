import test from "node:test";
import assert from "node:assert/strict";
import { runAgent, validateProposal } from "../lib/agent.mjs";
import {
  createExperiment,
  signExperiment,
  signingKey,
  readExperiment,
  signAudit,
  verifyAudit,
} from "../lib/experiment.mjs";
import { Store } from "../lib/store.mjs";
import experimentHandler from "../api/experiment.mjs";
import paymentHandler from "../api/payments.mjs";
import agentHandler from "../api/agent.mjs";
const secret = "test-secret-only-".repeat(3);
const serverSecret = "server-only-fixture-signing-key-32-chars";
function tool(name, args = {}) {
  return {
    id: crypto.randomUUID(),
    type: "function",
    function: { name, arguments: JSON.stringify(args) },
  };
}
function observations(messages) {
  return messages
    .filter((m) => m.role === "tool")
    .map((m) => JSON.parse(m.content))
    .filter((x) => x.tool);
}
// This deterministic provider exists ONLY in this test file, never in production.
function fakeModel(
  action,
  {
    twice = false,
    badRefs = false,
    failAfterProposal = false,
    assertHidden = false,
  } = {},
) {
  let step = 0;
  return async (messages) => {
    if (assertHidden)
      assert.ok(
        !JSON.stringify(messages).includes("outage"),
        "intervention leaked to model",
      );
    step++;
    if (step === 1)
      return {
        requestId: "test-provider-id",
        message: {
          tool_calls: [
            ...["catalog", "cart", "payment"].map((service) =>
              tool("probe_service", { service }),
            ),
            tool("test_payment"),
            ...(twice ? [tool("test_payment")] : []),
          ],
        },
      };
    const evidence = observations(messages);
    if (step === 2)
      return {
        message: {
          tool_calls: [
            tool("propose_action", {
              action,
              reason: "Decisão baseada nos resultados das ferramentas.",
              evidence_ids: badRefs ? ["invented"] : evidence.map((x) => x.id),
            }),
          ],
        },
      };
    if (failAfterProposal) throw new Error("private-provider-key");
    return {
      message: {
        content: JSON.stringify({
          outcome: action === "isolate_checkout" ? "incident" : "no_incident",
          summary: "Resultado de fixture de teste, não de IA real.",
          evidence_ids: evidence.map((x) => x.id),
        }),
      },
    };
  };
}
function res() {
  return {
    code: 200,
    headers: {},
    setHeader(k, v) {
      this.headers[k] = v;
    },
    status(c) {
      this.code = c;
      return this;
    },
    json(d) {
      this.data = d;
      return this;
    },
  };
}
const auth = { authorization: `Bearer ${secret}` };

test("model tool calls drive isolation; intervention is not included in model context", async () => {
  const state = { ...createExperiment(), fault: "outage" };
  const run = await runAgent({
    state,
    model: "test-fixture",
    modelCall: fakeModel("isolate_checkout", { assertHidden: true }),
  });
  assert.equal(run.status, "completed");
  assert.equal(run.applied.after, "open");
  assert.equal(run.applied.source, "agent");
  assert.equal(
    run.observations.find((x) => x.tool === "test_payment").status,
    503,
  );
  assert.ok(run.trace.some((x) => x.type === "policy_decision" && x.accepted));
  assert.ok(run.trace.some((x) => x.type === "action_applied"));
  assert.equal(
    state.checkout,
    "closed",
    "orchestrator must not mutate external state before handler commits",
  );
});
test("decline cannot authorize technical isolation", async () => {
  const run = await runAgent({
    state: { ...createExperiment(), fault: "declined" },
    model: "fixture",
    modelCall: fakeModel("isolate_checkout"),
  });
  assert.equal(run.status, "failed");
  assert.equal(run.applied, null);
  assert.equal(run.decision.accepted, false);
});
test("available services and a none proposal produce no intervention", async () => {
  const run = await runAgent({
    state: createExperiment(),
    model: "fixture",
    modelCall: fakeModel("none"),
  });
  assert.equal(run.status, "completed");
  assert.equal(run.applied, null);
  assert.ok(run.trace.some((x) => x.type === "no_action"));
});
test("resume needs two functional verifications and refuses pending payments", async () => {
  const state = { ...createExperiment(), checkout: "open" };
  const single = await runAgent({
    state,
    model: "fixture",
    modelCall: fakeModel("resume_checkout"),
  });
  assert.equal(single.status, "failed");
  const pending = await runAgent({
    state,
    pending: true,
    model: "fixture",
    modelCall: fakeModel("resume_checkout", { twice: true }),
  });
  assert.equal(pending.status, "failed");
  const valid = await runAgent({
    state,
    model: "fixture",
    modelCall: fakeModel("resume_checkout", { twice: true }),
  });
  assert.equal(valid.status, "completed");
  assert.equal(valid.applied.after, "closed");
});
test("provider failure after accepted proposal never applies it", async () => {
  const run = await runAgent({
    state: { ...createExperiment(), fault: "outage" },
    model: "fixture",
    modelCall: fakeModel("isolate_checkout", { failAfterProposal: true }),
  });
  assert.equal(run.status, "failed");
  assert.equal(run.applied, null);
  assert.ok(run.decision.accepted);
  assert.ok(!JSON.stringify(run).includes("private-provider-key"));
});
test("invented references and unknown tools cannot mutate state", async () => {
  const state = { ...createExperiment(), fault: "outage" };
  const run = await runAgent({
    state,
    model: "fixture",
    modelCall: fakeModel("isolate_checkout", { badRefs: true }),
  });
  assert.equal(run.applied, null);
  const unknown = await runAgent({
    state,
    model: "fixture",
    modelCall: async () => ({
      message: { tool_calls: [tool("execute_shell", { command: "anything" })] },
    }),
  });
  assert.equal(unknown.status, "failed");
  assert.equal(unknown.applied, null);
  assert.equal(
    validateProposal(
      { action: "none", reason: "x", evidence_ids: ["x", "x"] },
      [{ id: "x" }],
      state,
      false,
    ).accepted,
    false,
  );
});
test("signed experiments reject tampering, expiry and changed audit records", () => {
  const state = createExperiment(),
    token = signExperiment(state, secret);
  assert.equal(readExperiment(token, secret).id, state.id);
  assert.throws(() => readExperiment(token + "x", secret));
  assert.throws(() => readExperiment(token, secret, state.expiresAt + 1));
  const run = { id: "fixture", trace: [] },
    signature = signAudit(run, secret);
  assert.equal(verifyAudit(run, signature, secret), true);
  assert.equal(
    verifyAudit({ ...run, id: "changed" }, signature, secret),
    false,
  );
});
test("injection only changes fault; authenticated server enforcement blocks isolated checkout", () => {
  const backup = { ...process.env };
  process.env.OBS_DEMO_TOKEN = secret;
  process.env.OBS_EXPERIMENT_SECRET = serverSecret;
  try {
    const state = createExperiment();
    let result = res();
    experimentHandler(
      {
        method: "POST",
        headers: {
          ...auth,
          "x-experiment-state": signExperiment(state, serverSecret),
        },
        body: { operation: "inject", scenario: "outage" },
      },
      result,
    );
    assert.equal(result.code, 200);
    const next = readExperiment(result.data.stateToken, serverSecret);
    assert.equal(next.checkout, "closed");
    assert.equal(next.fault, "outage");
    next.checkout = "open";
    result = res();
    paymentHandler(
      {
        method: "POST",
        headers: { "x-experiment-state": signExperiment(next, serverSecret) },
        body: {
          operation: "pay",
          scenario: "normal",
          attemptId: "fixture-attempt",
          items: [{ id: "speaker", quantity: 1 }],
        },
      },
      result,
    );
    assert.equal(result.code, 423);
    assert.equal(result.data.source, "agent");
    result = res();
    experimentHandler(
      { method: "POST", headers: {}, body: { operation: "create" } },
      result,
    );
    assert.equal(result.code, 401);
  } finally {
    process.env = backup;
  }
});
test("client injection does not isolate; only completed current run applies and releases once", async () => {
  const state = { ...createExperiment(), fault: "outage" },
    s = new Store({
      call: async () => {
        throw new Error("unexpected payment");
      },
    });
  s.add("speaker");
  s.connectExperiment({
    experiment: { id: state.id, revision: state.revision, checkout: "closed" },
    stateToken: "test-token",
  });
  s.injectExperiment(
    {
      experiment: {
        id: state.id,
        revision: state.revision,
        checkout: "closed",
      },
      stateToken: "test-token",
    },
    "outage",
  );
  assert.equal(s.state.breaker, "closed");
  const run = await runAgent({
    state,
    model: "fixture",
    modelCall: fakeModel("isolate_checkout"),
  });
  s.applyAgentRun({
    run,
    signature: "fixture",
    stateToken: "new-test-token",
    experiment: { id: state.id, revision: 1, checkout: "open" },
  });
  assert.equal(s.state.breaker, "open");
  assert.equal(s.state.actionSource, "agent");
  s.subscribe();
  const recovered = {
    ...state,
    checkout: "open",
    fault: "normal",
    revision: 1,
  };
  const recovery = await runAgent({
    state: recovered,
    model: "fixture",
    modelCall: fakeModel("resume_checkout", { twice: true }),
  });
  s.applyAgentRun({
    run: recovery,
    signature: "fixture",
    stateToken: "new-token",
    experiment: { id: state.id, revision: 2, checkout: "closed" },
  });
  assert.equal(s.state.breaker, "closed");
  assert.equal(s.state.notices.length, 1);
  assert.equal(s.state.cart.length, 1);
  assert.throws(
    () => s.applyAgentRun({ run, signature: "stale" }),
    /desatualizada/,
  );
});
test("unconfigured production route reports unavailable instead of fabricating an agent", async () => {
  const backup = { ...process.env };
  try {
    process.env.OBS_DEMO_TOKEN = secret;
    process.env.OBS_EXPERIMENT_SECRET = serverSecret;
    delete process.env.OBS_LLM_URL;
    delete process.env.OBS_LLM_API_KEY;
    delete process.env.OBS_LLM_MODEL;
    let result = res();
    await agentHandler({ method: "GET", headers: {} }, result);
    assert.equal(result.data.configured, false);
    result = res();
    await agentHandler(
      {
        method: "POST",
        headers: auth,
        body: {
          operation: "run",
          pendingPayment: false,
          modelResponse: "fake",
        },
      },
      result,
    );
    assert.equal(result.code, 503);
    assert.equal(result.data.run, undefined);
  } finally {
    process.env = backup;
  }
});
test("HTTP agent route commits signed action only after valid model completion and verifies its audit", async () => {
  const backup = { ...process.env },
    original = globalThis.fetch;
  Object.assign(process.env, {
    OBS_DEMO_TOKEN: secret,
    OBS_EXPERIMENT_SECRET: serverSecret,
    OBS_LLM_URL: "https://fixture.invalid/v1",
    OBS_LLM_MODEL: "TEST_FIXTURE_NOT_REAL_IA",
    OBS_LLM_API_KEY: "test-only-key",
  });
  const fake = fakeModel("isolate_checkout", { assertHidden: true });
  globalThis.fetch = async (url, options) => {
    assert.equal(new URL(url).hostname, "fixture.invalid");
    const request = JSON.parse(options.body);
    const completion = await fake(request.messages);
    return {
      ok: true,
      headers: new Headers({ "x-request-id": "fixture-provider-request" }),
      text: async () =>
        JSON.stringify({ choices: [{ message: completion.message }] }),
    };
  };
  try {
    const state = { ...createExperiment(), fault: "outage" },
      result = res();
    await agentHandler(
      {
        method: "POST",
        headers: {
          ...auth,
          "x-experiment-state": signExperiment(state, serverSecret),
        },
        body: {
          operation: "run",
          pendingPayment: false,
          scenario: "normal",
          fakeAction: "resume_checkout",
        },
      },
      result,
    );
    assert.equal(result.code, 200);
    assert.equal(result.data.run.status, "completed");
    const next = readExperiment(result.data.stateToken, serverSecret);
    assert.equal(next.checkout, "open");
    assert.equal(next.revision, 1);
    const verify = res();
    await agentHandler(
      {
        method: "POST",
        headers: auth,
        body: {
          operation: "verify",
          run: result.data.run,
          signature: result.data.signature,
        },
      },
      verify,
    );
    assert.equal(verify.data.valid, true);
    const changed = structuredClone(result.data.run);
    changed.applied.after = "closed";
    const invalid = res();
    await agentHandler(
      {
        method: "POST",
        headers: auth,
        body: {
          operation: "verify",
          run: changed,
          signature: result.data.signature,
        },
      },
      invalid,
    );
    assert.equal(invalid.data.valid, false);
  } finally {
    globalThis.fetch = original;
    process.env = backup;
  }
});
test("executor only runs tools actually selected by the model", async () => {
  let turn = 0;
  const run = await runAgent({
    state: { ...createExperiment(), fault: "outage" },
    model: "fixture",
    modelCall: async (messages) => {
      if (++turn === 1)
        return {
          message: {
            tool_calls: [tool("probe_service", { service: "payment" })],
          },
        };
      return {
        message: {
          content: JSON.stringify({
            outcome: "incident",
            summary: "Fixture",
            evidence_ids: observations(messages).map((x) => x.id),
          }),
        },
      };
    },
  });
  assert.equal(run.observations.length, 1);
  assert.equal(run.observations[0].service, "payment");
  assert.equal(run.status, "failed");
  assert.equal(run.applied, null);
});
test("invalid final citation cancels an already accepted proposal", async () => {
  const fake = fakeModel("isolate_checkout");
  let turn = 0;
  const run = await runAgent({
    state: { ...createExperiment(), fault: "outage" },
    model: "fixture",
    modelCall: async (messages) => {
      const result = await fake(messages);
      if (++turn === 3)
        result.message.content = JSON.stringify({
          outcome: "incident",
          summary: "Fixture",
          evidence_ids: ["fabricated-final-reference"],
        });
      return result;
    },
  });
  assert.ok(run.decision.accepted);
  assert.equal(run.status, "failed");
  assert.equal(run.applied, null);
});

test("presenter token cannot forge server experiment or audit signatures", () => {
  const env = {
    OBS_DEMO_TOKEN: secret,
    OBS_LLM_API_KEY: "server-only-provider-fixture",
  };
  const key = signingKey(env),
    state = createExperiment();
  assert.notEqual(key, secret);
  assert.throws(() => readExperiment(signExperiment(state, secret), key));
  assert.equal(
    verifyAudit({ id: "fixture" }, signAudit({ id: "fixture" }, secret), key),
    false,
  );
  assert.throws(() =>
    signingKey({ OBS_DEMO_TOKEN: secret, OBS_EXPERIMENT_SECRET: secret }),
  );
});
