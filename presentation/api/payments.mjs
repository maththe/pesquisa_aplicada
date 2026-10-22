import { payment } from "../lib/payment.mjs";
import { readExperiment, signingKey } from "../lib/experiment.mjs";

export default function handler(req, res) {
  res.setHeader("Cache-Control", "no-store");
  res.setHeader("X-Content-Type-Options", "nosniff");
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ error: "Use POST." });
  }
  let body = req.body;
  try {
    if (typeof body === "string") body = JSON.parse(body);
  } catch {
    return res.status(400).json({ error: "JSON inválido." });
  }
  if (req.headers?.["x-experiment-state"]) {
    try {
      const state = readExperiment(
        req.headers["x-experiment-state"],
        signingKey(),
      );
      if (body?.operation === "pay" && state.checkout === "open") {
        return res.status(423).json({
          outcome: "isolated",
          source: "agent",
          error: "Finalização isolada pelo agente.",
        });
      }
      body = { ...body, scenario: state.fault };
    } catch (error) {
      return res
        .status(error.status || 401)
        .json({ error: "Experimento expirado ou inválido." });
    }
  }
  const [status, payload] = payment(body);
  res.setHeader(
    "X-Request-ID",
    /^[\w-]{1,100}$/.test(body?.attemptId || "")
      ? body.attemptId
      : "demo-probe",
  );
  return res.status(status).json(payload);
}
