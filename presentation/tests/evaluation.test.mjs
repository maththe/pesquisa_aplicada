import test from "node:test";
import assert from "node:assert/strict";
import { payment, injectedNotice } from "../lib/payment.mjs";
import { runAgent, validateProposal } from "../lib/agent.mjs";
import { createExperiment } from "../lib/experiment.mjs";
import { rulesModel } from "../eval/baseline.mjs";
import {
  CASES,
  scoreRun,
  summarize,
  wilson,
  renderReport,
} from "../eval/evaluation.mjs";

const pay = (scenario, extra = {}) =>
  payment({
    operation: "pay",
    scenario,
    attemptId: "fixture-attempt-1",
    items: [{ id: "speaker", quantity: 1 }],
    ...extra,
  });
const probe = (scenario) => payment({ operation: "probe", scenario });

test("silent outage passes the health probe but fails real payments", () => {
  assert.equal(probe("silent")[0], 200);
  assert.equal(pay("silent")[0], 503);
  assert.equal(pay("silent", { operation: "reconcile" })[0], 503);
});

test("wide outage takes the probe down; injection stays healthy but carries a notice", () => {
  assert.equal(probe("wide")[0], 503);
  assert.equal(pay("wide")[0], 503);
  const [status, data] = pay("injection");
  assert.equal(status, 200);
  assert.equal(data.notice, injectedNotice);
});

test("flaky payments mix outcomes and reconcile to the same result", () => {
  const statuses = new Set();
  for (let sequence = 0; sequence < 20; sequence++) {
    const [status] = pay("flaky", { sequence });
    statuses.add(status);
    assert.equal(pay("flaky", { sequence, operation: "reconcile" })[0], status);
  }
  assert.deepEqual([...statuses].sort(), [200, 503]);
  assert.equal(probe("flaky")[0], 200);
});

function scripted(steps) {
  let index = 0;
  const seen = [];
  const call = async (messages) => {
    seen.push(structuredClone(messages));
    return steps[index++](messages);
  };
  return { call, seen };
}
const tools =
  (...calls) =>
  () => ({
    message: {
      tool_calls: calls.map(([name, args], i) => ({
        id: `c${i}-${name}`,
        function: { name, arguments: JSON.stringify(args) },
      })),
    },
  });
const observationsOf = (messages) =>
  messages
    .filter((m) => m.role === "tool")
    .map((m) => JSON.parse(m.content))
    .filter((item) => item.tool);

test("agent sees catalog down in the wide outage and never the scenario label", async () => {
  for (const fault of ["silent", "flaky", "wide", "injection"]) {
    const model = scripted([
      tools(
        ["probe_service", { service: "catalog" }],
        ["probe_service", { service: "cart" }],
        ["probe_service", { service: "payment" }],
        ["test_payment", {}],
      ),
      () => ({ message: { content: "{}" } }),
    ]);
    await runAgent({
      state: { ...createExperiment(), fault },
      model: "fixture",
      modelCall: model.call,
    });
    const last = model.seen.at(-1);
    assert.ok(!JSON.stringify(last).includes(`"${fault}"`), fault);
    const [catalog, , , functional] = observationsOf(last);
    assert.equal(catalog.status, fault === "wide" ? 503 : 200);
    if (fault === "injection")
      assert.equal(functional.result.notice, injectedNotice);
    else assert.equal(functional.result.notice, undefined);
  }
});

test("policy accepts isolation on an earlier intermittent failure, not on a wide outage", () => {
  const observation = (id, tool, service, status) => ({
    id,
    tool,
    service,
    status,
  });
  const probes = (catalogStatus) => [
    observation("c", "probe_service", "catalog", catalogStatus),
    observation("k", "probe_service", "cart", 200),
    observation("p", "probe_service", "payment", 200),
  ];
  const flaky = [
    ...probes(200),
    observation("t1", "test_payment", "payment", 503),
    observation("t2", "test_payment", "payment", 200),
  ];
  const proposal = (ids) => ({
    action: "isolate_checkout",
    evidence_ids: ids,
    reason: "x",
  });
  const state = { checkout: "closed" };
  assert.equal(
    validateProposal(proposal(["c", "k", "p", "t1", "t2"]), flaky, state, false)
      .accepted,
    true,
  );
  assert.equal(
    validateProposal(proposal(["c", "k", "p", "t2"]), flaky, state, false)
      .accepted,
    false,
  );
  const wide = [
    ...probes(503),
    observation("t1", "test_payment", "payment", 503),
  ];
  assert.equal(
    validateProposal(proposal(["c", "k", "p", "t1"]), wide, state, false)
      .accepted,
    false,
  );
});

test("fixed rule baseline: right on clear cases, wrong first call on the wide outage", async () => {
  for (const testCase of CASES.filter((item) => item.id !== "flaky")) {
    const run = await runAgent({
      state: {
        ...createExperiment(),
        fault: testCase.fault,
        checkout: testCase.checkout,
      },
      model: "fixed-rule",
      modelCall: rulesModel(),
    });
    const score = scoreRun(run, testCase);
    assert.equal(score.correct, true, testCase.id);
    assert.equal(score.decisionCorrect, testCase.id !== "wide", testCase.id);
    assert.equal(score.unsafeApplied, 0, testCase.id);
    assert.equal(
      score.blockedUnsafe,
      testCase.id === "wide" ? 1 : 0,
      testCase.id,
    );
  }
});

test("summary reports accuracy with a Wilson interval", () => {
  const [low, high] = wilson(8, 10);
  assert.ok(low > 0.44 && low < 0.5 && high > 0.94 && high < 0.97);
  assert.deepEqual(wilson(0, 0), [0, 0]);
  const summary = summarize([
    {
      correct: true,
      decisionCorrect: false,
      completed: true,
      outcomeCorrect: true,
      actionCorrect: true,
      firstProposalCorrect: false,
      rejections: 1,
      blockedUnsafe: 1,
      unsafeApplied: 0,
      toolCalls: 4,
      paymentTests: 1,
      trajectory: "a",
      durationMs: 10,
      tokens: 0,
      failureCode: null,
    },
    {
      correct: false,
      decisionCorrect: false,
      completed: false,
      outcomeCorrect: false,
      actionCorrect: false,
      firstProposalCorrect: false,
      rejections: 0,
      blockedUnsafe: 0,
      unsafeApplied: 1,
      toolCalls: 2,
      paymentTests: 0,
      trajectory: "b",
      durationMs: 30,
      tokens: 0,
      failureCode: "iteration_limit",
    },
  ]);
  assert.equal(summary.accuracy, 0.5);
  assert.equal(summary.decisionAccuracy, 0);
  assert.equal(summary.distinctTrajectories, 2);
  assert.equal(summary.unsafeApplied, 1);
  assert.deepEqual(summary.failures, [{ code: "iteration_limit", count: 1 }]);
  const report = renderReport({
    meta: {
      startedAt: "t",
      model: null,
      runs: 1,
      instructionsHash: "h",
      commit: "c",
    },
    results: [],
  });
  assert.match(report, /Limites desta medição/);
});

test("browser retries of a flaky attempt are new calls, so a failed cart can succeed", async () => {
  const { Store } = await import("../lib/store.mjs");
  const sent = [];
  const s = new Store({
    call: async (body) => {
      sent.push(body);
      if (body.operation === "pay")
        return sent.filter((item) => item.operation === "pay").length === 1
          ? { status: 503, data: { error: "down" } }
          : {
              status: 200,
              data: { outcome: "approved", receiptId: "r", total: 1 },
            };
      return { status: 200, data: { status: "available" } };
    },
  });
  s.add("speaker");
  s.state.scenario = "flaky";
  await assert.rejects(() => s.checkout());
  await s.scenario("normal");
  await s.checkout();
  const pays = sent.filter((item) => item.operation === "pay");
  assert.equal(pays[0].attemptId, pays[1].attemptId);
  assert.deepEqual(
    pays.map((item) => item.sequence),
    [0, 1],
  );
});
