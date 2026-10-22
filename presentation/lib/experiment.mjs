import { createHmac, timingSafeEqual, randomUUID } from "node:crypto";
export class AccessError extends Error {
  constructor(message, status = 401) {
    super(message);
    this.status = status;
  }
}
export function presenter(req, env = process.env) {
  const token = env.OBS_DEMO_TOKEN;
  if (!token || token.length < 32)
    throw new AccessError("Configure OBS_DEMO_TOKEN na Vercel.", 503);
  const expected = Buffer.from(`Bearer ${token}`),
    actual = Buffer.from(req.headers.authorization || "");
  if (expected.length !== actual.length || !timingSafeEqual(expected, actual))
    throw new AccessError("Token do apresentador inválido.", 401);
  return token;
}
export function signingKey(env = process.env) {
  if (
    env.OBS_EXPERIMENT_SECRET?.length >= 32 &&
    env.OBS_EXPERIMENT_SECRET !== env.OBS_DEMO_TOKEN
  )
    return env.OBS_EXPERIMENT_SECRET;
  if (!env.OBS_LLM_API_KEY)
    throw new AccessError(
      "Configure a chave do provedor ou OBS_EXPERIMENT_SECRET no servidor.",
      503,
    );
  // Separate signing authority from the presenter token that the browser knows.
  return createHmac("sha256", env.OBS_LLM_API_KEY)
    .update("nexo-experiment-signing-v1")
    .digest("hex");
}
function mac(value, secret) {
  return createHmac("sha256", secret).update(value).digest("base64url");
}
export function signExperiment(state, secret) {
  const body = Buffer.from(JSON.stringify(state)).toString("base64url");
  return body + "." + mac(body, secret);
}
export function readExperiment(token, secret, now = Date.now()) {
  if (
    typeof token !== "string" ||
    token.length > 8000 ||
    !secret ||
    secret.length < 32
  )
    throw new AccessError("Experimento inválido.");
  const [body, signature, extra] = token.split(".");
  const expected = Buffer.from(mac(body || "", secret)),
    actual = Buffer.from(signature || "");
  if (
    extra ||
    expected.length !== actual.length ||
    !timingSafeEqual(expected, actual)
  )
    throw new AccessError("Assinatura do experimento inválida.");
  let state;
  try {
    state = JSON.parse(Buffer.from(body, "base64url").toString());
  } catch {
    throw new AccessError("Experimento inválido.");
  }
  if (
    state.version !== 1 ||
    !["normal", "outage", "slow", "declined"].includes(state.fault) ||
    !["closed", "open"].includes(state.checkout) ||
    !Number.isInteger(state.revision) ||
    state.expiresAt <= now
  )
    throw new AccessError("Experimento expirado ou inválido.");
  return state;
}
export function createExperiment() {
  return {
    version: 1,
    id: randomUUID(),
    revision: 0,
    fault: "normal",
    checkout: "closed",
    expiresAt: Date.now() + 60 * 60 * 1000,
  };
}
export function publicExperiment(state) {
  return {
    id: state.id,
    revision: state.revision,
    checkout: state.checkout,
    expiresAt: state.expiresAt,
  };
}
export function signAudit(run, secret) {
  return mac(JSON.stringify(run), secret);
}
export function verifyAudit(run, signature, secret) {
  if (typeof signature !== "string") return false;
  const a = Buffer.from(signAudit(run, secret)),
    b = Buffer.from(signature);
  return a.length === b.length && timingSafeEqual(a, b);
}
export function parseBody(req) {
  try {
    return typeof req.body === "string" ? JSON.parse(req.body) : req.body;
  } catch {
    throw new AccessError("JSON inválido.", 400);
  }
}
