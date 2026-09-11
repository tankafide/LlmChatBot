import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import openapiTS, { astToString } from "openapi-typescript";
const dir = mkdtempSync(join(tmpdir(), "autoassist-schema-"));
try {
  const schema = process.env.OPENAPI_FILE
    ? readFileSync(process.env.OPENAPI_FILE, "utf8")
    : execFileSync(
        "uv",
        [
          "run",
          "--project",
          "../backend",
          "python",
          "../scripts/export-openapi.py",
        ],
        { encoding: "utf8" },
      );
  const path = join(dir, "openapi.json");
  writeFileSync(path, schema);
  const output = astToString(
    await openapiTS(new URL(`file:///${path.replaceAll("\\", "/")}`)),
  );
  const target = resolve("src/api/generated.ts");
  if (process.argv.includes("--check")) {
    if (readFileSync(target, "utf8") !== output)
      throw new Error("API types have drifted. Run npm run api:generate.");
  } else writeFileSync(target, output);
} finally {
  rmSync(dir, { recursive: true, force: true });
}
