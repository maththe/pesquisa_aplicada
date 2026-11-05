import { presenter } from "../lib/experiment.mjs";
import { EVENT_TYPES, MAX_READ, logStore, readEvents } from "../lib/log.mjs";

export default async function handler(req, res) {
  res.setHeader("Cache-Control", "no-store");
  res.setHeader("X-Content-Type-Options", "nosniff");
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return res.status(405).json({ error: "Use GET." });
  }
  try {
    presenter(req);
  } catch (error) {
    return res.status(error.status || 401).json({ error: error.message });
  }
  if (!logStore())
    return res.status(503).json({
      configured: false,
      error: "Configure o Upstash Redis na Vercel para salvar os logs.",
    });
  const query = new URL(req.url || "/", "http://localhost").searchParams;
  const limit = Number(query.get("limit") || 100);
  const type = query.get("type");
  if (!Number.isInteger(limit) || limit < 1 || limit > MAX_READ)
    return res
      .status(400)
      .json({ error: `Informe limit entre 1 e ${MAX_READ}.` });
  if (type && !EVENT_TYPES.includes(type))
    return res
      .status(400)
      .json({ error: `Tipo inválido. Use ${EVENT_TYPES.join(", ")}.` });
  try {
    const { events, truncated } = await readEvents({ limit, type });
    // truncated: the response hit its size cap; ask for a smaller limit or a type.
    return res
      .status(200)
      .json({ configured: true, count: events.length, truncated, events });
  } catch {
    return res
      .status(502)
      .json({ configured: true, error: "Não foi possível ler os logs." });
  }
}
