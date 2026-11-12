import test from "node:test";
import assert from "node:assert/strict";
import { payment, catalog } from "../lib/payment.mjs";
import { Store, PRODUCTS, fresh, readState, rules } from "../lib/store.mjs";
import { validateDiagnosis } from "../api/diagnose.mjs";
const items = [{ id: "headphones", quantity: 1 }];
const body = {
  operation: "pay",
  scenario: "normal",
  attemptId: "test-attempt-123",
  items,
};
const call = async (body) => {
  const [status, data] = payment(body);
  return { status, data };
};

test("catalog and server totals are authoritative and consistent", () => {
  assert.deepEqual(
    PRODUCTS.map((p) => [p.id, p.price]),
    catalog.map((p) => [p.id, p.price]),
  );
  const [status, result] = payment({
    ...body,
    total: 1,
    items: [{ ...items[0], price: 1 }],
  });
  assert.equal(status, 200);
  assert.equal(result.total, 18990);
  assert.equal(result.sandbox, true);
});
test("same attempt and canonical cart yield same receipt", () => {
  const a = payment({
    ...body,
    items: [...items, { id: "keyboard", quantity: 2 }],
  });
  const b = payment({
    ...body,
    items: [{ id: "keyboard", quantity: 2 }, ...items],
  });
  assert.equal(a[1].receiptId, b[1].receiptId);
  assert.notEqual(
    a[1].receiptId,
    payment({ ...body, attemptId: "different-attempt" })[1].receiptId,
  );
});
test("rejects invalid products, quantities, duplicates and payloads", () => {
  for (const invalid of [
    null,
    {},
    { ...body, scenario: "arbitrary" },
    { ...body, items: [] },
    { ...body, items: [{ id: "unknown", quantity: 1 }] },
    { ...body, items: [{ id: "headphones", quantity: 1.1 }] },
    { ...body, items: [...items, ...items] },
    { ...body, items: [{ id: "headphones", quantity: 21 }] },
  ])
    assert.equal(payment(invalid)[0], 400);
});
test("outage, timeout and decline have distinct HTTP semantics", () => {
  assert.equal(payment({ ...body, scenario: "outage" })[0], 503);
  assert.equal(payment({ ...body, scenario: "slow" })[0], 504);
  assert.equal(payment({ ...body, scenario: "declined" })[0], 402);
  assert.equal(
    payment({ ...body, operation: "probe", scenario: "declined" })[0],
    200,
  );
});
test("cart persists, circuit avoids payments and notice is delivered once", async () => {
  const s = new Store({ call });
  s.add("headphones");
  await s.scenario("outage");
  s.subscribe();
  const state = readState({ getItem: () => JSON.stringify(s.state) });
  const restored = new Store({ state, call });
  await assert.rejects(() => restored.checkout(), /indisponível/);
  assert.equal(
    restored.state.evidence.filter((e) => e.event === "payment_pay").length,
    0,
  );
  await restored.scenario("normal");
  await restored.scenario("normal");
  assert.equal(restored.state.notices.length, 1);
  assert.equal(restored.state.cart.length, 1);
  await restored.checkout();
  assert.equal(restored.state.orders.length, 1);
  assert.equal(restored.state.cart.length, 0);
});
test("decline preserves cart without opening the circuit", async () => {
  const s = new Store({ call });
  s.add("speaker");
  await s.scenario("declined");
  await assert.rejects(() => s.checkout(), /recusado/);
  assert.equal(s.state.breaker, "closed");
  assert.equal(s.state.cart.length, 1);
});
test("timeout survives reload and reconciliation uses the original attempt", async () => {
  const s = new Store({ call });
  s.add("keyboard");
  await s.scenario("slow");
  await assert.rejects(() => s.checkout(), /desconhecida/);
  const id = s.state.attempt.id;
  const restored = new Store({
    call,
    state: readState({ getItem: () => JSON.stringify(s.state) }),
  });
  await assert.rejects(() => restored.checkout(), /pendente/);
  assert.throws(() => restored.add("speaker"), /pendente/);
  await assert.rejects(() => restored.scenario("normal"), /Reconcilie/);
  const receipt = await restored.reconcile();
  assert.equal(receipt.attemptId, id);
  assert.equal(restored.state.orders.length, 1);
  await assert.rejects(() => restored.reconcile(), /Nenhum/);
});
test("failed recovery cannot close the circuit or emit a notice", async () => {
  const s = new Store({ call });
  s.add("speaker");
  await s.scenario("outage");
  s.subscribe();
  s.call = async () => ({ status: 503, data: { status: "unavailable" } });
  assert.equal(await s.scenario("normal"), false);
  assert.equal(s.state.breaker, "open");
  assert.equal(s.state.notices.length, 0);
});
test("lost response preserves ambiguous attempt and blocks another charge", async () => {
  const s = new Store({
    call: async () => {
      throw new Error("network unavailable");
    },
  });
  s.add("speaker");
  await assert.rejects(() => s.checkout(), /network/);
  const id = s.state.attempt.id;
  await assert.rejects(() => s.checkout(), /pendente/);
  assert.equal(s.state.attempt.id, id);
  assert.equal(s.state.cart.length, 1);
});
test("invalid persisted cart is not trusted", () => {
  assert.deepEqual(readState({ getItem: () => "{broken" }), fresh());
  assert.deepEqual(
    readState({
      getItem: () =>
        JSON.stringify({ ...fresh(), cart: [{ id: "no", quantity: 1 }] }),
    }),
    fresh(),
  );
});
test("diagnosis rejects invented references and labels rules separately", () => {
  const evidence = [{ id: "real-id", status: 503 }];
  assert.throws(() =>
    validateDiagnosis(
      { outcome: "incident", summary: "error", evidence_ids: ["invented"] },
      evidence,
    ),
  );
  assert.equal(
    validateDiagnosis(
      { outcome: "incident", summary: "error", evidence_ids: ["real-id"] },
      evidence,
    ).outcome,
    "incident",
  );
  assert.equal(rules(evidence).mode, "rules");
});
test("network error during recovery leaves the circuit open", async () => {
  const s = new Store({ call });
  s.add("speaker");
  await s.scenario("outage");
  s.subscribe();
  s.call = async () => {
    throw new Error("network");
  };
  assert.equal(await s.scenario("normal"), false);
  assert.equal(s.state.breaker, "open");
  assert.equal(s.state.notices.length, 0);
});
test("lost normal payment response can be reconciled in the deterministic sandbox", async () => {
  const s = new Store({
    call: async () => {
      throw new Error("network");
    },
  });
  s.add("speaker");
  await assert.rejects(() => s.checkout());
  const id = s.state.attempt.id;
  s.call = call;
  const receipt = await s.reconcile();
  assert.equal(receipt.attemptId, id);
  assert.equal(s.state.orders.length, 1);
});
test("retry after recovery records the actual scenario before reconciliation", async () => {
  const s = new Store({ call });
  s.add("speaker");
  s.state.scenario = "outage";
  await assert.rejects(() => s.checkout());
  await s.scenario("normal");
  s.call = async () => {
    throw new Error("lost response");
  };
  await assert.rejects(() => s.checkout());
  assert.equal(s.state.attempt.scenario, "normal");
  s.call = call;
  await s.reconcile();
  assert.equal(s.state.orders.length, 1);
});
