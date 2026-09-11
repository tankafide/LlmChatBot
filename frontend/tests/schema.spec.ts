import { test, expect } from "@playwright/test";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("offline schema is deterministic and an isolated schema change fails drift", () => {
  const dir = mkdtempSync(join(tmpdir(), "autoassist-drift-"));
  const committed = readFileSync("src/api/generated.ts", "utf8");
  try {
    const script =
      'import json, socket, sqlite3; from autoassist.app import create_app; socket.create_connection = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")); sqlite3.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError("database")); print(json.dumps(create_app().openapi(), sort_keys=True))';
    const exportSchema = () =>
      spawnSync(
        "uv",
        ["run", "--project", "../backend", "python", "-c", script],
        {
          encoding: "utf8",
          env: {
            ...process.env,
            AUTOASSIST_CONFIG_FILE: join(dir, "absent.json"),
            AUTOASSIST_DATABASE_URL: `sqlite:///${join(dir, "must-not-exist.db")}`,
          },
        },
      );
    const first = exportSchema();
    const second = exportSchema();
    expect(first.status, first.stderr).toBe(0);
    expect(second.status, second.stderr).toBe(0);
    expect(first.stdout).toBe(second.stdout);
    const schema: unknown = JSON.parse(first.stdout);
    const altered = { ...(schema as object), paths: {} };
    const file = join(dir, "changed.json");
    writeFileSync(file, JSON.stringify(altered));
    const drift = spawnSync(process.execPath, ["scripts/api.mjs", "--check"], {
      encoding: "utf8",
      env: { ...process.env, OPENAPI_FILE: file },
    });
    expect(drift.status).not.toBe(0);
    expect(drift.stderr).toContain("API types have drifted");
    expect(readFileSync("src/api/generated.ts", "utf8")).toBe(committed);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
