import http from "node:http";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import payments from "./api/payments.mjs";
import diagnose from "./api/diagnose.mjs";
import agent from "./api/agent.mjs";
import experiment from "./api/experiment.mjs";
const root = path.dirname(fileURLToPath(import.meta.url));
const server = http.createServer(async (req, res) => {
  const pathname = new URL(req.url, "http://localhost").pathname;
  res.status = (code) => {
    res.statusCode = code;
    return res;
  };
  res.json = (value) => {
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(value));
  };
  try {
    const handlers = {
      "/api/payments": payments,
      "/api/diagnose": diagnose,
      "/api/agent": agent,
      "/api/experiment": experiment,
    };
    if (handlers[pathname]) {
      let body = "";
      for await (const chunk of req) {
        body += chunk;
        if (body.length > 30000)
          return res.status(413).json({ error: "Corpo acima do limite." });
      }
      try {
        req.body = body ? JSON.parse(body) : null;
      } catch {
        return res.status(400).json({ error: "JSON inválido." });
      }
      return await handlers[pathname](req, res);
    }
    const files = {
      "/": "index.html",
      "/index.html": "index.html",
      "/store.css": "store.css",
      "/store.mjs": "store.mjs",
      "/lib/store.mjs": "lib/store.mjs",
      "/docker.html": "docker.html",
    };
    if (!files[pathname]) return res.status(404).end("Not found");
    res.setHeader(
      "Content-Type",
      pathname.endsWith(".css")
        ? "text/css"
        : pathname.endsWith(".mjs")
          ? "text/javascript"
          : "text/html; charset=utf-8",
    );
    res.end(await readFile(path.join(root, files[pathname])));
  } catch {
    res.status(500).json({ error: "Falha no servidor local." });
  }
});
server.listen(Number(process.env.PORT || 3100), "127.0.0.1", () =>
  console.log("Servidor de demonstração iniciado."),
);
