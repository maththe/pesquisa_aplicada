import {
  presenter,
  signingKey,
  parseBody,
  readExperiment,
  signExperiment,
  publicExperiment,
  signAudit,
  verifyAudit,
} from "../lib/experiment.mjs";
import { runAgent, providerClient } from "../lib/agent.mjs";
export default async function handler(req, res) {
  res.setHeader("Cache-Control", "no-store");
  const env = process.env;
  const configured = Boolean(
    env.OBS_LLM_URL &&
      env.OBS_LLM_MODEL &&
      env.OBS_LLM_API_KEY &&
      env.OBS_DEMO_TOKEN?.length >= 32,
  );
  if (req.method === "GET")
    return res
      .status(200)
      .json({ configured, model: configured ? env.OBS_LLM_MODEL : null });
  if (req.method !== "POST")
    return res.status(405).json({ error: "Use POST." });
  try {
    presenter(req);
    const secret = signingKey(env),
      body = parseBody(req);
    if (body?.operation === "verify") {
      if (
        !body.run ||
        typeof body.signature !== "string" ||
        JSON.stringify(body.run).length > 90000
      )
        return res.status(400).json({ error: "Registro acima do limite." });
      return res
        .status(200)
        .json({ valid: verifyAudit(body.run, body.signature, secret) });
    }
    if (!configured)
      return res.status(503).json({
        error: "Configure o provedor de IA na Vercel.",
        configured: false,
      });
    if (body?.operation !== "run" || typeof body.pendingPayment !== "boolean")
      return res.status(400).json({ error: "Solicitação inválida." });
    const state = readExperiment(req.headers["x-experiment-state"], secret);
    const run = await runAgent({
      state,
      pending: body.pendingPayment,
      model: env.OBS_LLM_MODEL,
      modelCall: providerClient(env, AbortSignal.timeout(45000)),
    });
    if (run.applied) {
      state.checkout = run.applied.after;
      state.revision++;
    }
    return res.status(run.status === "completed" ? 200 : 502).json({
      run,
      signature: signAudit(run, secret),
      stateToken: signExperiment(state, secret),
      experiment: publicExperiment(state),
    });
  } catch (error) {
    return res.status(error.status || 502).json({
      error: error.status
        ? error.message
        : "Agente indisponível. Nenhuma ação aplicada.",
    });
  }
}
