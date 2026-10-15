/* Starts the Django server the Playwright suite runs against.
 *
 *   1. builds the web app (skip with E2E_SKIP_BUILD=1 when it is current)
 *   2. checks the settings Django really resolved (a developer's .env wins over
 *      environment variables, so a stray DATABASE_URL must never get through)
 *   3. migrate + seed_demo --reset on a throwaway SQLite file in the OS temp dir
 *   4. runserver on 127.0.0.1:$E2E_PORT, serving the BUILT app (no Vite)
 *
 * Plain node on purpose: it runs unchanged on Windows and Linux. Set PYTHON to
 * the interpreter that has the project's requirements (default: python).
 */
import { spawn, spawnSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(frontendDir, "..");
const python = process.env.PYTHON || "python";
const port = process.env.E2E_PORT || "8799";

const workDir = path.join(tmpdir(), "autumn-e2e");
const dbFile = path.join(workDir, "e2e.sqlite3").replaceAll("\\", "/");
const mediaDir = path.join(workDir, "media").replaceAll("\\", "/");
rmSync(workDir, { recursive: true, force: true });
mkdirSync(mediaDir, { recursive: true });
// Profiles default to media/default.jpg; serve the tracked copy from the temp media root.
const defaultAvatar = path.join(repoRoot, "media", "default.jpg");
if (existsSync(defaultAvatar)) copyFileSync(defaultAvatar, path.join(mediaDir, "default.jpg"));

const env = {
  ...process.env,
  SECRET_KEY: process.env.SECRET_KEY || "e2e-only-secret-key-not-for-anything-real",
  DATABASE_URL: `sqlite:///${dbFile}`,
  MEDIA_ROOT: mediaDir,
  DEBUG: "TRUE",
  VITE_DEV_SERVER: "",
  RUN_REMINDER_DISPATCHER: "FALSE",
  SEMANTIC_SYNC_ON_WRITE: "FALSE",
  USE_S3: "FALSE",
  // Nothing in the suite may reach an LLM or embedding provider.
  OPENAI_API_KEY: "",
  GEMINI_API_KEY: "",
  ANTHROPIC_API_KEY: "",
  OPENROUTER_API_KEY: "",
  PYTHONUNBUFFERED: "1",
  PYTHONIOENCODING: "utf-8",
};

function fail(message) {
  console.error(`[e2e server] ${message}`);
  process.exit(1);
}

function run(label, command, args, options = {}) {
  console.log(`[e2e server] ${label}`);
  const result = spawnSync(command, args, { stdio: "inherit", env, ...options });
  if (result.status !== 0) fail(`${label} failed (${result.status ?? result.error})`);
}

if (!process.env.E2E_SKIP_BUILD) {
  // shell: npm is npm.cmd on Windows, which spawn cannot run directly.
  run("npm run build", "npm run build", [], { cwd: frontendDir, shell: true });
}

const probe = spawnSync(
  python,
  [
    "manage.py",
    "shell",
    "-c",
    "import json; from django.conf import settings as s; " +
      "print('SETTINGS=' + json.dumps({'debug': s.DEBUG, 'db': str(s.DATABASES['default']['NAME']), " +
      "'vite': s.VITE_DEV_SERVER, 's3': bool(s.USE_S3)}))",
  ],
  { cwd: repoRoot, env, encoding: "utf-8" },
);
const line = (probe.stdout ?? "").split("\n").find((l) => l.startsWith("SETTINGS="));
if (probe.status !== 0 || !line) {
  fail(`could not read Django settings (is PYTHON=${python} set up?):\n${probe.stderr ?? ""}`);
}
const resolved = JSON.parse(line.slice("SETTINGS=".length));
const normalise = (p) => path.resolve(p).replaceAll("\\", "/").toLowerCase();
if (!resolved.debug || resolved.vite || resolved.s3 || normalise(resolved.db) !== normalise(dbFile)) {
  fail(
    `Django resolved unexpected settings ${JSON.stringify(resolved)}; expected DEBUG on, ` +
      `no VITE_DEV_SERVER, no S3 and database ${dbFile}. A .env file overrides the environment, ` +
      "so check it for DEBUG, DATABASE_URL, USE_S3 and VITE_DEV_SERVER.",
  );
}

run("migrate", python, ["manage.py", "migrate", "--noinput"], { cwd: repoRoot });
run("seed_demo --reset", python, ["manage.py", "seed_demo", "--reset"], { cwd: repoRoot });

console.log(`[e2e server] serving http://127.0.0.1:${port}`);
const server = spawn(python, ["manage.py", "runserver", `127.0.0.1:${port}`, "--noreload"], {
  cwd: repoRoot,
  env,
  stdio: "inherit",
});
const stop = () => server.kill();
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
process.on("exit", stop);
server.on("exit", (code) => process.exit(code ?? 0));
