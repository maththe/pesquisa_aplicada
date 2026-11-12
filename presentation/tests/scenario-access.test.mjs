import test from "node:test";
import assert from "node:assert/strict";
import { fresh, readState } from "../lib/store.mjs";

test("cenários iniciam sem exigir conexão com agente", () => {
  assert.equal(fresh().controlMode, "rules");
});
test("sessão antiga sem agente conectado libera cenários e preserva carrinho e pagamento pendente", () => {
  const previous = {
    ...fresh(),
    controlMode: "agent",
    cart: [{ id: "headphones", quantity: 2 }],
    attempt: { id: "pending", unknown: true },
  };
  const state = readState({ getItem: () => JSON.stringify(previous) });
  assert.equal(state.controlMode, "rules");
  assert.deepEqual(state.cart, previous.cart);
  assert.deepEqual(state.attempt, previous.attempt);
});
test("sessão conectada mantém a escolha explícita do agente", () => {
  const previous = {
    ...fresh(),
    controlMode: "agent",
    agentExperiment: { token: "signed-session" },
  };
  assert.equal(
    readState({ getItem: () => JSON.stringify(previous) }).controlMode,
    "agent",
  );
});
