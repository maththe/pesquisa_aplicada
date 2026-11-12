import { randomUUID } from "node:crypto";

// Server-side event log kept in Upstash Redis through its REST API, so the
// functions stay free of npm dependencies. Without configuration, logging is off
// and every handler keeps working exactly as before.
export const LOG_PREFIX = "nexo:logs:";
export const MAX_EVENTS = 2000;
export const MAX_READ = 500;
export const EVENT_TYPES = ["payment", "experiment", "agent_run", "diagnosis"];
const RETENTION_SECONDS = 30 * 24 * 60 * 60;
// Above the 90,000-char limit of /api/agent verify, so stored runs stay verifiable.
const MAX_EVENT_CHARS = 100000;
// Vercel caps a function response at 4.5 MB; stop reading well before that.
const MAX_READ_CHARS = 3_500_000;
const WRITE_TIMEOUT_MS = 1500;
const READ_TIMEOUT_MS = 5000;

// One list per type: anonymous payment traffic cannot evict agent runs.
export const logKey = (type) => LOG_PREFIX + type;

export function logStore(env = process.env) {
  const url = env.UPSTASH_REDIS_REST_URL || env.KV_REST_API_URL;
  const token = env.UPSTASH_REDIS_REST_TOKEN || env.KV_REST_API_TOKEN;
  if (!url || !token) return null;
  try {
    const endpoint = new URL(url);
    if (endpoint.protocol !== "https:") return null;
    return { url: endpoint.href.replace(/\/$/, ""), token };
  } catch {
    return null;
  }
}

async function send(store, path, body, fetchImpl, timeout) {
  const response = await fetchImpl(store.url + path, {
    method: "POST",
    signal: AbortSignal.timeout(timeout),
    headers: {
      Authorization: `Bearer ${store.token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error("Log store failure");
  return response.json();
}

function serialize(entry) {
  const value = JSON.stringify(entry);
  if (value.length <= MAX_EVENT_CHARS) return value;
  return JSON.stringify({
    id: entry.id,
    at: entry.at,
    type: entry.type,
    truncated: true,
    size: value.length,
  });
}

// Never throws: a log outage must not change the outcome of a purchase or agent run.
export async function recordEvent(
  event,
  { env = process.env, fetchImpl = globalThis.fetch } = {},
) {
  const store = logStore(env);
  if (!store) return { stored: false, reason: "not_configured" };
  if (!EVENT_TYPES.includes(event.type))
    return { stored: false, reason: "unknown_type" };
  const entry = { id: randomUUID(), at: new Date().toISOString(), ...event };
  const key = logKey(event.type);
  try {
    const results = await send(
      store,
      "/pipeline",
      [
        ["LPUSH", key, serialize(entry)],
        ["LTRIM", key, "0", String(MAX_EVENTS - 1)],
        ["EXPIRE", key, String(RETENTION_SECONDS)],
      ],
      fetchImpl,
      WRITE_TIMEOUT_MS,
    );
    if (!Array.isArray(results) || results.some((item) => item?.error))
      throw new Error("Log store rejected the event");
    return { stored: true, id: entry.id };
  } catch {
    return { stored: false, reason: "store_failure" };
  }
}

// Newest first. Without a type, merges the latest `limit` events of every type.
export async function readEvents({
  limit = 100,
  type = null,
  env = process.env,
  fetchImpl = globalThis.fetch,
} = {}) {
  const store = logStore(env);
  if (!store) throw new Error("Log store not configured");
  const types = type ? [type] : EVENT_TYPES;
  const replies = await send(
    store,
    "/pipeline",
    types.map((item) => ["LRANGE", logKey(item), "0", String(limit - 1)]),
    fetchImpl,
    READ_TIMEOUT_MS,
  );
  if (
    !Array.isArray(replies) ||
    replies.some((item) => item?.error || !Array.isArray(item?.result))
  )
    throw new Error("Invalid log store reply");
  const events = [];
  for (const raw of replies.flatMap((item) => item.result)) {
    try {
      events.push({ event: JSON.parse(raw), size: raw.length });
    } catch {
      // Skip entries that are not valid JSON instead of failing the whole read.
    }
  }
  events.sort((a, b) => String(b.event.at).localeCompare(String(a.event.at)));
  const selected = [];
  let size = 0;
  let truncated = false;
  for (const item of events.slice(0, limit)) {
    if (size + item.size > MAX_READ_CHARS) {
      truncated = true;
      break;
    }
    size += item.size;
    selected.push(item.event);
  }
  return { events: selected, truncated };
}
