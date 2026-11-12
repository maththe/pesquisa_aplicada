import test from "node:test";
import assert from "node:assert/strict";
import {
  MAX_EVENTS,
  logKey,
  logStore,
  readEvents,
  recordEvent,
} from "../lib/log.mjs";
import logsHandler from "../api/logs.mjs";
import payments from "../api/payments.mjs";

const env = {
  UPSTASH_REDIS_REST_URL: "https://example-redis.upstash.io/",
  UPSTASH_REDIS_REST_TOKEN: "test-token-only",
};
const presenterToken = "p".repeat(32);

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

function fakeStore(
  reply = () => [{ result: 1 }, { result: "OK" }, { result: 1 }],
) {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options, body: JSON.parse(options.body) });
    return { ok: true, json: async () => reply(url) };
  };
  return { calls, fetchImpl };
}

async function withEnv(values, fn) {
  const backup = { ...process.env },
    original = globalThis.fetch;
  try {
    for (const name of [
      "UPSTASH_REDIS_REST_URL",
      "UPSTASH_REDIS_REST_TOKEN",
      "KV_REST_API_URL",
      "KV_REST_API_TOKEN",
      "OBS_EXPERIMENT_SECRET",
    ])
      delete process.env[name];
    Object.assign(process.env, values);
    return await fn();
  } finally {
    process.env = backup;
    globalThis.fetch = original;
  }
}

test("log store is off without credentials or over plain HTTP", async () => {
  assert.equal(logStore({}), null);
  assert.equal(
    logStore({
      ...env,
      UPSTASH_REDIS_REST_URL: "http://example-redis.upstash.io",
    }),
    null,
  );
  assert.deepEqual(
    logStore({
      KV_REST_API_URL: "https://kv.example.io",
      KV_REST_API_TOKEN: "t",
    }),
    { url: "https://kv.example.io", token: "t" },
  );
  const { calls, fetchImpl } = fakeStore();
  assert.deepEqual(
    await recordEvent({ type: "payment" }, { env: {}, fetchImpl }),
    {
      stored: false,
      reason: "not_configured",
    },
  );
  assert.equal(calls.length, 0);
});

test("recordEvent pushes a capped, expiring entry with bearer auth", async () => {
  const { calls, fetchImpl } = fakeStore();
  const result = await recordEvent(
    { type: "payment", status: 503 },
    { env, fetchImpl },
  );
  assert.equal(result.stored, true);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "https://example-redis.upstash.io/pipeline");
  assert.equal(
    calls[0].options.headers.Authorization,
    "Bearer test-token-only",
  );
  const [push, trim, expire] = calls[0].body;
  assert.deepEqual(push.slice(0, 2), ["LPUSH", logKey("payment")]);
  const entry = JSON.parse(push[2]);
  assert.equal(entry.type, "payment");
  assert.equal(entry.status, 503);
  assert.equal(entry.id, result.id);
  assert.ok(Date.parse(entry.at));
  assert.deepEqual(trim, [
    "LTRIM",
    logKey("payment"),
    "0",
    String(MAX_EVENTS - 1),
  ]);
  assert.equal(expire[0], "EXPIRE");
});

test("recordEvent never throws when the store fails or rejects", async () => {
  const down = async () => {
    throw new Error("network down");
  };
  assert.deepEqual(
    await recordEvent({ type: "payment" }, { env, fetchImpl: down }),
    {
      stored: false,
      reason: "store_failure",
    },
  );
  const rejected = fakeStore(() => [{ error: "WRONGTYPE" }]);
  const result = await recordEvent(
    { type: "payment" },
    { env, fetchImpl: rejected.fetchImpl },
  );
  assert.equal(result.stored, false);
});

test("oversized events are replaced by a truncation marker", async () => {
  const { calls, fetchImpl } = fakeStore();
  await recordEvent(
    { type: "agent_run", run: "x".repeat(110000) },
    { env, fetchImpl },
  );
  await recordEvent(
    { type: "agent_run", run: "y".repeat(85000) },
    { env, fetchImpl },
  );
  assert.equal(JSON.parse(calls[1].body[0][2]).run.length, 85000);
  const entry = JSON.parse(calls[0].body[0][2]);
  assert.equal(entry.truncated, true);
  assert.equal(entry.type, "agent_run");
  assert.equal(entry.run, undefined);
});

test("readEvents reads one list per type, merges newest first and skips malformed entries", async () => {
  const lists = {
    [logKey("payment")]: [
      JSON.stringify({ id: "p2", type: "payment", at: "2026-11-05T10:02:00Z" }),
      "{broken",
      JSON.stringify({ id: "p1", type: "payment", at: "2026-11-05T10:00:00Z" }),
    ],
    [logKey("agent_run")]: [
      JSON.stringify({
        id: "a1",
        type: "agent_run",
        at: "2026-11-05T10:01:00Z",
      }),
    ],
  };
  const calls = [];
  const fetchImpl = async (url, options) => {
    const body = JSON.parse(options.body);
    calls.push({ url, body });
    return {
      ok: true,
      json: async () => body.map(([, key]) => ({ result: lists[key] || [] })),
    };
  };
  const one = await readEvents({ limit: 1, type: "agent_run", env, fetchImpl });
  assert.deepEqual(calls[0].body, [["LRANGE", logKey("agent_run"), "0", "0"]]);
  assert.deepEqual(
    one.events.map((event) => event.id),
    ["a1"],
  );
  const all = await readEvents({ limit: 10, env, fetchImpl });
  assert.equal(calls[1].body.length, 4);
  assert.deepEqual(
    all.events.map((event) => event.id),
    ["p2", "a1", "p1"],
  );
  assert.equal(all.truncated, false);
});

test("readEvents stops before the response size cap", async () => {
  const big = JSON.stringify({
    id: "x",
    type: "agent_run",
    at: "2026-11-05T10:00:00Z",
    run: "z".repeat(99000),
  });
  const fetchImpl = async () => ({
    ok: true,
    json: async () => [{ result: Array(50).fill(big) }],
  });
  const result = await readEvents({
    limit: 50,
    type: "agent_run",
    env,
    fetchImpl,
  });
  assert.equal(result.truncated, true);
  assert.ok(result.events.length < 50 && result.events.length > 30);
});

test("logs endpoint requires presenter token and configuration", async () =>
  withEnv({ OBS_DEMO_TOKEN: presenterToken }, async () => {
    let res = response();
    await logsHandler({ method: "POST", headers: {} }, res);
    assert.equal(res.code, 405);
    res = response();
    await logsHandler({ method: "GET", headers: {}, url: "/api/logs" }, res);
    assert.equal(res.code, 401);
    res = response();
    const auth = { authorization: "Bearer " + presenterToken };
    await logsHandler({ method: "GET", headers: auth, url: "/api/logs" }, res);
    assert.equal(res.code, 503);
    assert.equal(res.data.configured, false);
  }));

test("logs endpoint validates query and returns stored events", async () =>
  withEnv({ ...env, OBS_DEMO_TOKEN: presenterToken }, async () => {
    const auth = { authorization: "Bearer " + presenterToken };
    globalThis.fetch = fakeStore(() => [
      { result: [JSON.stringify({ id: "1", type: "payment" })] },
    ]).fetchImpl;
    let res = response();
    await logsHandler(
      { method: "GET", headers: auth, url: "/api/logs?limit=0" },
      res,
    );
    assert.equal(res.code, 400);
    res = response();
    await logsHandler(
      { method: "GET", headers: auth, url: "/api/logs?limit=501" },
      res,
    );
    assert.equal(res.code, 400);
    res = response();
    await logsHandler(
      { method: "GET", headers: auth, url: "/api/logs?type=secret" },
      res,
    );
    assert.equal(res.code, 400);
    res = response();
    await logsHandler(
      { method: "GET", headers: auth, url: "/api/logs?type=payment" },
      res,
    );
    assert.equal(res.code, 200);
    assert.equal(res.data.count, 1);
    assert.equal(res.headers["Cache-Control"], "no-store");
  }));

test("payment handler stores the outcome and still answers if the store is down", async () =>
  withEnv(env, async () => {
    const store = fakeStore();
    globalThis.fetch = store.fetchImpl;
    const body = {
      operation: "pay",
      scenario: "outage",
      attemptId: "valid-attempt-123",
      items: [{ id: "speaker", quantity: 1 }],
    };
    let res = response();
    await payments({ method: "POST", body }, res);
    assert.equal(res.code, 503);
    const entry = JSON.parse(store.calls[0].body[0][2]);
    assert.equal(entry.type, "payment");
    assert.equal(entry.mode, "rules");
    assert.equal(entry.status, 503);
    assert.equal(entry.outcome, "unavailable");
    assert.equal(entry.attemptId, "valid-attempt-123");
    assert.equal(entry.items, undefined);

    globalThis.fetch = async () => {
      throw new Error("store down");
    };
    res = response();
    await payments(
      { method: "POST", body: { ...body, scenario: "normal" } },
      res,
    );
    assert.equal(res.code, 200);
    assert.equal(res.data.outcome, "approved");
  }));

test("malformed payment requests are not logged", async () =>
  withEnv(env, async () => {
    const store = fakeStore();
    globalThis.fetch = store.fetchImpl;
    const res = response();
    await payments(
      { method: "POST", body: { operation: "pay", scenario: "bad" } },
      res,
    );
    assert.equal(res.code, 400);
    assert.equal(store.calls.length, 0);
  }));

test("agent runs are stored with their signature, even when the provider fails", async () => {
  const { createExperiment, signExperiment } =
    await import("../lib/experiment.mjs");
  const { default: agentHandler } = await import("../api/agent.mjs");
  const serverSecret = "s".repeat(40);
  return withEnv(
    {
      ...env,
      OBS_DEMO_TOKEN: presenterToken,
      OBS_EXPERIMENT_SECRET: serverSecret,
      OBS_LLM_URL: "https://provider.example/v1",
      OBS_LLM_MODEL: "test-model",
      OBS_LLM_API_KEY: "test-value-only",
    },
    async () => {
      const store = fakeStore();
      globalThis.fetch = async (url, options) => {
        if (String(url).startsWith("https://example-redis.upstash.io"))
          return store.fetchImpl(url, options);
        return { ok: false, text: async () => "" };
      };
      const state = createExperiment();
      const res = response();
      await agentHandler(
        {
          method: "POST",
          headers: {
            authorization: "Bearer " + presenterToken,
            "x-experiment-state": signExperiment(state, serverSecret),
          },
          body: { operation: "run", pendingPayment: false },
        },
        res,
      );
      assert.equal(res.code, 502);
      assert.equal(store.calls.length, 1);
      const entry = JSON.parse(store.calls[0].body[0][2]);
      assert.equal(entry.type, "agent_run");
      assert.equal(entry.status, "failed");
      assert.equal(entry.experimentId, state.id);
      assert.equal(entry.action, null);
      assert.equal(entry.signature, res.data.signature);
      assert.deepEqual(entry.run, res.data.run);
      assert.ok(!JSON.stringify(entry).includes("test-value-only"));
    },
  );
});
