// Runs every evaluation case N times per arm and writes the evidence folder.
//
//   cd presentation
//   node --env-file=../.env eval/run.mjs --runs 10
//
// Options: --runs N (default 5), --arms agent,agent_minimal,rules,naive_probe,
// --cases id,id, --concurrency N (default 3), --out <folder>.
// The agent and agent_minimal arms need OBS_LLM_URL, OBS_LLM_MODEL and OBS_LLM_API_KEY
// and make paid calls to that provider. The rules and naive_probe arms make none.
import { mkdir, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import {
  instructions,
  minimalInstructions,
  providerClient,
  runAgent,
} from "../lib/agent.mjs";
import { createExperiment } from "../lib/experiment.mjs";
import { rulesModel, naiveProbeModel } from "./baseline.mjs";
import {
  ARMS,
  CASES,
  renderReport,
  scoreRun,
  summarize,
} from "./evaluation.mjs";

const root = path.dirname(fileURLToPath(import.meta.url));
const { values } = parseArgs({
  options: {
    runs: { type: "string", default: "5" },
    arms: { type: "string", default: "agent,rules,naive_probe" },
    cases: { type: "string" },
    concurrency: { type: "string", default: "3" },
    out: { type: "string" },
  },
});
const runs = Number(values.runs);
const concurrency = Number(values.concurrency);
const arms = values.arms.split(",");
const cases = values.cases
  ? CASES.filter((item) => values.cases.split(",").includes(item.id))
  : CASES;
if (
  !Number.isInteger(runs) ||
  runs < 1 ||
  runs > 100 ||
  !Number.isInteger(concurrency) ||
  concurrency < 1 ||
  concurrency > 10 ||
  !cases.length ||
  arms.some((arm) => !(arm in ARMS))
) {
  console.error("Opções inválidas. Veja o cabeçalho de eval/run.mjs.");
  process.exit(1);
}
const env = process.env;
const usesLlm = arms.includes("agent") || arms.includes("agent_minimal");
if (
  usesLlm &&
  !(env.OBS_LLM_URL && env.OBS_LLM_MODEL && env.OBS_LLM_API_KEY)
) {
  console.error(
    "Os braços agent e agent_minimal exigem OBS_LLM_URL, OBS_LLM_MODEL e OBS_LLM_API_KEY. Use --env-file=../.env ou --arms rules,naive_probe.",
  );
  process.exit(1);
}

let commit = null;
try {
  commit = execFileSync("git", ["rev-parse", "--short", "HEAD"], {
    cwd: root,
    encoding: "utf8",
  }).trim();
  const dirty = execFileSync("git", ["status", "--porcelain"], {
    cwd: root,
    encoding: "utf8",
  }).trim();
  // Uncommitted changes mean the commit alone does not reproduce this run.
  if (dirty) commit += " + alterações não commitadas";
} catch {
  // Not a git checkout; the report says "desconhecido".
}
const startedAt = new Date().toISOString();
const meta = {
  startedAt,
  model: usesLlm ? env.OBS_LLM_MODEL : null,
  runs,
  arms,
  cases: cases.map((item) => item.id),
  instructionsHash: createHash("sha256")
    .update(instructions)
    .digest("hex")
    .slice(0, 16),
  minimalInstructionsHash: createHash("sha256")
    .update(minimalInstructions)
    .digest("hex")
    .slice(0, 16),
  commit,
};

const jobs = [];
for (const testCase of cases)
  for (const arm of arms)
    for (let index = 0; index < runs; index++)
      jobs.push({ testCase, arm, index });

async function execute(job) {
  try {
    return await attempt(job);
  } catch {
    // A harness or configuration error is recorded as a failed run, not a lost batch.
    const now = new Date().toISOString();
    const run = {
      id: null,
      status: "failed",
      trace: [],
      startedAt: now,
      finishedAt: now,
      failureCode: "harness_error",
    };
    console.log(
      `ERRO ${job.testCase.id.padEnd(9)} ${job.arm.padEnd(13)} #${job.index + 1} harness_error`,
    );
    return {
      case: job.testCase.id,
      arm: job.arm,
      index: job.index,
      runId: null,
      score: scoreRun(run, job.testCase),
      run,
    };
  }
}

async function attempt({ testCase, arm, index }) {
  const state = {
    ...createExperiment(),
    fault: testCase.fault,
    checkout: testCase.checkout,
  };
  const isLlm = arm === "agent" || arm === "agent_minimal";
  const run = await runAgent({
    state,
    pending: false,
    model: isLlm
      ? env.OBS_LLM_MODEL
      : arm === "naive_probe"
        ? "naive-probe"
        : "fixed-rule",
    promptProfile: arm === "agent_minimal" ? "minimal" : "prescriptive",
    modelCall: isLlm
      ? providerClient(env, AbortSignal.timeout(60000))
      : arm === "naive_probe"
        ? naiveProbeModel()
        : rulesModel(),
  });
  const score = scoreRun(run, testCase);
  console.log(
    `${score.correct ? "ok  " : "ERRO"} ${testCase.id.padEnd(9)} ${arm.padEnd(13)} #${index + 1} ${score.outcome ?? "-"} / ${score.finalAction ?? run.failureCode}`,
  );
  return { case: testCase.id, arm, index, runId: run.id, score, run };
}

const results = [];
let next = 0;
await Promise.all(
  Array.from({ length: Math.min(concurrency, jobs.length) }, async () => {
    while (next < jobs.length) results.push(await execute(jobs[next++]));
  }),
);
results.sort(
  (a, b) =>
    CASES.findIndex((c) => c.id === a.case) -
      CASES.findIndex((c) => c.id === b.case) ||
    a.arm.localeCompare(b.arm) ||
    a.index - b.index,
);
meta.finishedAt = new Date().toISOString();

const summary = {};
for (const testCase of cases)
  for (const arm of arms)
    summary[`${testCase.id}/${arm}`] = summarize(
      results
        .filter((item) => item.case === testCase.id && item.arm === arm)
        .map((item) => item.score),
    );
for (const arm of arms)
  summary[`todos/${arm}`] = summarize(
    results.filter((item) => item.arm === arm).map((item) => item.score),
  );

const stamp = startedAt.replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
const out = values.out
  ? path.resolve(values.out)
  : path.join(
      root,
      "..",
      "..",
      "docs",
      "evidencias",
      `avaliacao-agente-${stamp}`,
    );
await mkdir(out, { recursive: true });
await writeFile(
  path.join(out, "resultados.json"),
  JSON.stringify({ meta, cases, results }, null, 2),
);
await writeFile(
  path.join(out, "resumo.json"),
  JSON.stringify({ meta, summary }, null, 2),
);
await writeFile(
  path.join(out, "relatorio.md"),
  renderReport({ meta, results }),
);
for (const arm of arms) {
  const total = summary[`todos/${arm}`];
  console.log(`${arm}: ${total.correct}/${total.n} corretos`);
}
console.log(`Evidências em ${out}`);
