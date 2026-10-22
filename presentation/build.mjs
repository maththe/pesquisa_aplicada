import { mkdir, readFile, writeFile, copyFile } from "node:fs/promises";
const core = (await readFile("lib/store.mjs", "utf8")).replace(
  /^export /gm,
  "",
);
const app = (await readFile("store.mjs", "utf8"))
  .replace(/^import .*\n/, "")
  .replace(/^export /gm, "");
const css = await readFile("store.css", "utf8");
const html = (await readFile("page.html", "utf8"))
  .replace("/* STYLES */", () => css)
  .replace("/* APPLICATION */", () => core + "\n" + app);
await writeFile("index.html", html);
await mkdir("public", { recursive: true });
await writeFile("public/index.html", html);
await copyFile("docker.html", "public/docker.html");
