import {
  presenter,
  signingKey,
  parseBody,
  createExperiment,
  readExperiment,
  signExperiment,
  publicExperiment,
} from "../lib/experiment.mjs";
export default function handler(req, res) {
  res.setHeader("Cache-Control", "no-store");
  try {
    if (req.method !== "POST")
      return res.status(405).json({ error: "Use POST." });
    presenter(req);
    const secret = signingKey(),
      body = parseBody(req);
    if (!["create", "inject"].includes(body?.operation))
      return res.status(400).json({ error: "Operação inválida." });
    const state =
      body.operation === "create"
        ? createExperiment()
        : readExperiment(req.headers["x-experiment-state"], secret);
    if (body.operation === "inject") {
      if (!["normal", "outage", "slow", "declined"].includes(body.scenario))
        return res.status(400).json({ error: "Cenário inválido." });
      state.fault = body.scenario;
      state.revision++;
      // Injection never changes checkout isolation. Only an accepted agent action does.
    }
    return res.status(200).json({
      experiment: publicExperiment(state),
      stateToken: signExperiment(state, secret),
    });
  } catch (error) {
    return res.status(error.status || 500).json({
      error: error.status ? error.message : "Falha ao configurar experimento.",
    });
  }
}
