import { payment } from "../lib/payment.mjs";
import { readExperiment, signingKey } from "../lib/experiment.mjs";
import { recordEvent } from "../lib/log.mjs";

const attemptPattern = /^[\w-]{1,100}$/;

export default async function handler(req, res) {
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
  const attemptId = attemptPattern.test(body?.attemptId || "")
    ? body.attemptId
    : null;
  let experimentId = null;
  if (req.headers?.["x-experiment-state"]) {
    try {
      const state = readExperiment(
        req.headers["x-experiment-state"],
        signingKey(),
      );
      experimentId = state.id;
      if (body?.operation === "pay" && state.checkout === "open") {
        await recordEvent({
          type: "payment",
          mode: "agent",
          experimentId,
          operation: "pay",
          attemptId,
          status: 423,
          outcome: "isolated",
        });
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
  // Malformed requests are not logged, so noise cannot push real events out of the capped list.
  if (status !== 400)
    await recordEvent({
      type: "payment",
      mode: experimentId ? "agent" : "rules",
      experimentId,
      operation: body.operation,
      scenario: body.scenario,
      attemptId,
      status,
      outcome: payload.outcome ?? payload.status ?? null,
      receiptId: payload.receiptId ?? null,
      total: payload.total ?? null,
    });
  res.setHeader("X-Request-ID", attemptId || "demo-probe");
  return res.status(status).json(payload);
}
