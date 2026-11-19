import { cpSync, existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";

// Keep committed hashed assets available to pages opened before a deployment.
const archive = mkdtempSync(join(tmpdir(), "jyotish-assets-"));
const assets = resolve("out/_next/static");
try {
  if (existsSync(assets)) cpSync(assets, archive, { recursive: true });
  const result = spawnSync(process.execPath, ["node_modules/next/dist/bin/next", "build"], { stdio: "inherit" });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exitCode = result.status || 1;
  else cpSync(archive, assets, { recursive: true, force: false });
} finally {
  rmSync(archive, { recursive: true, force: true });
}
