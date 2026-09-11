import { test, expect } from "@playwright/test";
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { delimiter, join, resolve } from "node:path";

test("real API: imported inventory, safety, process restart and browser restoration", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const root = resolve("..");
  const python = join(
    root,
    "backend",
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
  );
  const dir = mkdtempSync(join(tmpdir(), "autoassist-browser-"));
  const config = join(dir, "dealerships.json");
  writeFileSync(
    config,
    JSON.stringify({
      connections: {
        fake: {
          provider: "xai",
          model: "test-model",
          api_key_env: "AUTOASSIST_BROWSER_TEST_KEY",
        },
      },
      dealerships: [
        { slug: "mia-motors", name: "Mia Motors", default_connection: "fake" },
      ],
    }),
  );
  const env = {
    ...process.env,
    AUTOASSIST_DATABASE_URL: `sqlite:///${join(dir, "chat.db").replaceAll("\\", "/")}`,
    AUTOASSIST_CONFIG_FILE: config,
    AUTOASSIST_BROWSER_TEST_KEY: "deterministic-test-key",
    PYTHONPATH: [
      join(root, "scripts"),
      join(root, "backend/tests"),
      join(root, "backend/src"),
    ].join(delimiter),
  };
  let server: ChildProcess | undefined;
  let output = "";
  async function start() {
    server = spawn(
      python,
      [
        "-m",
        "uvicorn",
        "browser_acceptance_app:app",
        "--host",
        "127.0.0.1",
        "--port",
        "18081",
        "--workers",
        "1",
      ],
      { cwd: root, env, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] },
    );
    server.stdout?.on("data", (chunk: Buffer) => {
      output += chunk.toString();
    });
    server.stderr?.on("data", (chunk: Buffer) => {
      output += chunk.toString();
    });
    await expect
      .poll(
        async () => {
          if (server?.exitCode !== null) throw new Error(output);
          try {
            return (await fetch("http://127.0.0.1:18081/health")).ok;
          } catch {
            return false;
          }
        },
        { timeout: 20_000 },
      )
      .toBe(true);
  }
  async function stop() {
    if (!server || server.exitCode !== null) return;
    const child = server;
    await new Promise<void>((resolveStop, reject) => {
      const timer = setTimeout(
        () => reject(new Error("Backend did not stop")),
        15_000,
      );
      child.once("exit", () => {
        clearTimeout(timer);
        resolveStop();
      });
      child.kill("SIGTERM");
    });
  }
  async function send(text: string, reply: RegExp) {
    await page.getByRole("textbox").fill(text);
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await expect(page.locator(".assistant").last()).toContainText(reply);
    await expect(page.getByRole("button", { name: "New chat" })).toBeEnabled();
  }
  try {
    // A green health endpoint alone must not certify a showroom with no inventory.
    await start();
    const emptySetup = spawnSync(
      python,
      [join(root, "scripts/check-setup.py"), "--url", "http://127.0.0.1:18081"],
      { env, encoding: "utf8", windowsHide: true },
    );
    expect(emptySetup.status).toBe(1);
    expect(emptySetup.stderr).toContain("Inventory is empty");
    await stop();
    const imported = spawnSync(
      python,
      [
        "-m",
        "autoassist.inventory.import_cli",
        "--file",
        join(root, "docs/context/inventory/data.csv"),
        "--dealership",
        "mia-motors",
        "--server-stopped",
      ],
      { cwd: root, env, encoding: "utf8", windowsHide: true },
    );
    expect(imported.status, imported.stderr).toBe(0);
    await start();
    const readySetup = spawnSync(
      python,
      [join(root, "scripts/check-setup.py"), "--url", "http://127.0.0.1:18081"],
      { env, encoding: "utf8", windowsHide: true },
    );
    expect(readySetup.status, readySetup.stderr).toBe(0);
    await page.goto("/");
    await expect(page.getByText("Mia Motors", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "New chat" })).toBeEnabled();
    await send("Show me Toyota RAV4 SUVs", /AA-1001/);
    await send("stock AA-1001", /AA-1001/);
    await send("What is its price?", /price:/);
    await send("recalls", /recall/i);
    await send("both", /NHTSA ID 202/);
    const previous = await page.locator(".message").allTextContents();
    await stop();
    await start();
    await page.reload();
    await expect(page.locator(".message")).toHaveCount(previous.length);
    expect(await page.locator(".message").allTextContents()).toEqual(previous);
    await send("202", /Overall: 5\/5/);
    await send("What is its price?", /price:/);
  } finally {
    await stop();
    rmSync(dir, {
      recursive: true,
      force: true,
      maxRetries: 5,
      retryDelay: 100,
    });
  }
});
