import test from "node:test";
import assert from "node:assert/strict";
import payments from "../api/payments.mjs";
import diagnose from "../api/diagnose.mjs";
function response() {
  return {
    code: 200,
    headers: {},
    setHeader(k, v) {
      this.headers[k] = v;
    },
    status(code) {
      this.code = code;
      return this;
    },
    json(data) {
      this.data = data;
      return this;
    },
  };
}
test("payment handler rejects unsupported method and malformed JSON", () => {
  let res = response();
  payments({ method: "GET" }, res);
  assert.equal(res.code, 405);
  res = response();
  payments({ method: "POST", body: "{broken" }, res);
  assert.equal(res.code, 400);
  res = response();
  payments(
    {
      method: "POST",
      body: {
        operation: "pay",
        scenario: "normal",
        attemptId: "valid-attempt-123",
        items: [null],
      },
    },
    res,
  );
  assert.equal(res.code, 400);
});
test("payment handler returns actual sandbox status and correlation", () => {
  const res = response();
  payments(
    {
      method: "POST",
      body: {
        operation: "pay",
        scenario: "outage",
        attemptId: "valid-attempt-123",
        items: [{ id: "speaker", quantity: 1 }],
      },
    },
    res,
  );
  assert.equal(res.code, 503);
  assert.equal(res.headers["X-Request-ID"], "valid-attempt-123");
  assert.equal(res.headers["Cache-Control"], "no-store");
  assert.equal(res.data.sandbox, true);
});
test("LLM missing config is explicit and does not invent a diagnosis", async () => {
  const backup = { ...process.env };
  try {
    for (const name of [
      "OBS_LLM_URL",
      "OBS_LLM_MODEL",
      "OBS_LLM_API_KEY",
      "OBS_DEMO_TOKEN",
    ])
      delete process.env[name];
    const res = response();
    await diagnose(
      { method: "POST", body: { evidence: [] }, headers: {} },
      res,
    );
    assert.equal(res.code, 503);
    assert.equal(res.data.configured, false);
    assert.equal(res.data.summary, undefined);
  } finally {
    process.env = backup;
  }
});
test("LLM requires presenter auth and validates cited evidence", async () => {
  const backup = { ...process.env },
    original = globalThis.fetch;
  try {
    Object.assign(process.env, {
      OBS_LLM_URL: "https://example.com/v1",
      OBS_LLM_MODEL: "test-model",
      OBS_LLM_API_KEY: "test-value-only",
      OBS_DEMO_TOKEN: "x".repeat(32),
    });
    let res = response();
    await diagnose(
      { method: "POST", body: { evidence: [{ id: "real-id" }] }, headers: {} },
      res,
    );
    assert.equal(res.code, 401);
    globalThis.fetch = async () => ({
      ok: true,
      text: async () =>
        JSON.stringify({
          choices: [
            {
              message: {
                content: JSON.stringify({
                  outcome: "incident",
                  summary: "Falha",
                  evidence_ids: ["invented-id"],
                }),
              },
            },
          ],
        }),
    });
    res = response();
    await diagnose(
      {
        method: "POST",
        body: { evidence: [{ id: "real-id" }] },
        headers: { authorization: "Bearer " + "x".repeat(32) },
      },
      res,
    );
    assert.equal(res.code, 502);
    globalThis.fetch = async () => ({
      ok: true,
      text: async () =>
        JSON.stringify({
          choices: [
            {
              message: {
                content: JSON.stringify({
                  outcome: "incident",
                  summary: "Falha observada",
                  evidence_ids: ["real-id"],
                }),
              },
            },
          ],
        }),
    });
    res = response();
    await diagnose(
      {
        method: "POST",
        body: { evidence: [{ id: "real-id" }] },
        headers: { authorization: "Bearer " + "x".repeat(32) },
      },
      res,
    );
    assert.equal(res.code, 200);
    assert.equal(res.data.mode, "llm");
  } finally {
    process.env = backup;
    globalThis.fetch = original;
  }
});
