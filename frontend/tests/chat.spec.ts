import { test, expect, type Page, type Route } from "@playwright/test";
import type { Message, Submission } from "../src/api/client";
const dealer = "11111111-1111-4111-8111-111111111111";
const conversation = "22222222-2222-4222-8222-222222222222";
const requestId = "33333333-3333-4333-8333-333333333333";
const storageKey = "autoassist:http://127.0.0.1:5173:mia-motors";
function row(
  sequence: number,
  request_id = requestId,
  text = "Show SUVs",
  status: Message["request_status"] = "completed",
): Message {
  return {
    id: `00000000-0000-4000-8000-${String(sequence).padStart(12, "0")}`,
    sequence,
    request_id,
    role: sequence % 2 ? "user" : "assistant",
    text,
    created_at: "2026-09-10T12:00:00Z",
    request_status: status,
    error_code: status === "failed" ? "provider_error" : null,
  };
}
async function saved(page: Page, pending = true) {
  await page.addInitScript(
    ({ key, conversation, requestId, pending }) =>
      localStorage.setItem(
        key,
        JSON.stringify({
          conversation,
          pending: pending
            ? { conversation, request_id: requestId, text: "Show SUVs" }
            : undefined,
        }),
      ),
    { key: storageKey, conversation, requestId, pending },
  );
}
type Harness = {
  posts: Submission[];
  creates: number;
  polls: number;
  onStatus?: (route: Route) => Promise<void>;
  onCreate?: (route: Route) => Promise<void>;
  history: Message[];
  onPost?: (route: Route, body: Submission) => Promise<void>;
  onHistory?: (route: Route) => Promise<void>;
};
async function harness(page: Page): Promise<Harness> {
  const h: Harness = { posts: [], creates: 0, polls: 0, history: [] };
  await page.route(/\/api\/(dealerships)(\/|$)/, async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/dealerships")
      return route.fulfill({
        json: {
          items: [{ id: dealer, slug: "mia-motors", name: "Mia Motors" }],
        },
      });
    if (url.pathname.includes("/requests/")) {
      h.polls++;
      if (h.onStatus) return h.onStatus(route);
      const id = url.pathname.split("/").at(-1);
      const user = h.history.find(
        (m) => m.request_id === id && m.role === "user",
      );
      const assistant = h.history.find(
        (m) => m.request_id === id && m.role === "assistant",
      );
      if (!user)
        return route.fulfill({
          status: 404,
          json: { error: { code: "not_found", message: "Request not found" } },
        });
      return route.fulfill({
        json: {
          conversation_id: conversation,
          request_id: id,
          status: user.request_status,
          ...(user.request_status === "in_progress"
            ? {}
            : {
                outcome:
                  user.request_status === "completed"
                    ? {
                        conversation_id: conversation,
                        request_id: id,
                        status: "completed",
                        user_message: user,
                        assistant_message: assistant,
                      }
                    : {
                        error: {
                          code: user.error_code ?? "request_interrupted",
                          message: "Terminal request error",
                        },
                      },
              }),
        },
      });
    }
    if (!url.pathname.endsWith("/messages")) {
      h.creates++;
      if (h.onCreate) return h.onCreate(route);
      return route.fulfill({ status: 201, json: { id: conversation } });
    }
    if (route.request().method() === "GET") {
      if (h.onHistory) return h.onHistory(route);
      return route.fulfill({
        json: {
          conversation_id: conversation,
          items: h.history,
          next_after_sequence: null,
        },
      });
    }
    const body = route.request().postDataJSON() as Submission;
    h.posts.push(body);
    if (h.onPost) return h.onPost(route, body);
    const user: Message = {
      ...row(h.history.length + 1, body.request_id, body.text),
      role: "user",
    };
    const assistant: Message = {
      ...row(h.history.length + 2, body.request_id, "A real inventory reply"),
      role: "assistant",
    };
    h.history.push(user, assistant);
    return route.fulfill({
      status: 202,
      json: {
        conversation_id: conversation,
        request_id: body.request_id,
        status: "in_progress",
      },
    });
  });
  return h;
}
async function send(page: Page, text = "Show SUVs") {
  await expect(page.getByRole("button", { name: "New chat" })).toBeEnabled();
  await page.getByRole("textbox").fill(text);
  await page.getByRole("button", { name: "Send", exact: true }).click();
}
test("send, multiline keyboard, no duplicates, reload and lazy new chat", async ({
  page,
}) => {
  const h = await harness(page);
  await page.goto("/");
  await expect(page.getByRole("textbox")).toBeEditable();
  await page.getByRole("textbox").fill("Toyota");
  await page.getByRole("textbox").press("Shift+Enter");
  await page.getByRole("textbox").press("x");
  await page.getByRole("textbox").press("Enter");
  await expect(
    page.getByText("A real inventory reply", { exact: true }),
  ).toHaveCount(1);
  expect(h.posts[0]?.text).toBe("Toyota\nx");
  await expect(page.getByRole("textbox")).toBeFocused();
  await page.reload();
  await expect(
    page.getByText("A real inventory reply", { exact: true }),
  ).toHaveCount(1);
  await page.getByRole("button", { name: "New chat" }).click();
  await expect(
    page.getByText("A real inventory reply", { exact: true }),
  ).toHaveCount(0);
  expect(h.creates).toBe(1);
});
test("long replies reveal quickly and open at their beginning", async ({
  page,
}) => {
  const h = await harness(page);
  const longReply = `${"Inventory detail line\n".repeat(120)}Final detail`;
  h.onPost = (route, body) => {
    const user = {
      ...row(1, body.request_id, body.text),
      role: "user" as const,
    };
    const assistant = {
      ...row(2, body.request_id, longReply),
      role: "assistant" as const,
    };
    h.history = [user, assistant];
    return route.fulfill({
      json: {
        conversation_id: conversation,
        request_id: body.request_id,
        status: "completed",
        user_message: user,
        assistant_message: assistant,
      },
    });
  };
  await page.goto("/");
  await send(page);
  const reply = page.locator(".assistant");
  await expect(reply.locator(".fast-reveal")).toHaveAttribute(
    "data-revealing",
    "true",
  );
  await expect(reply.locator(".fast-reveal")).toHaveAttribute(
    "data-revealing",
    "false",
    { timeout: 2_000 },
  );
  await expect(reply.locator(".fast-reveal")).toContainText("Final detail");
  await expect(page.getByRole("textbox")).toBeFocused();
  await expect
    .poll(() =>
      page.locator(".transcript").evaluate((transcript) => {
        const answer = transcript.querySelector(".assistant");
        if (!answer) return false;
        const viewport = transcript.getBoundingClientRect();
        const bounds = answer.getBoundingClientRect();
        return (
          bounds.top >= viewport.top &&
          bounds.top < viewport.top + transcript.clientHeight / 2
        );
      }),
    )
    .toBe(true);
  expect(
    await page.locator(".transcript").evaluate((transcript) => {
      const answer = transcript.querySelector(".assistant");
      return (
        !!answer &&
        answer.getBoundingClientRect().bottom >
          transcript.getBoundingClientRect().bottom
      );
    }),
  ).toBe(true);
});

test("manual history reading is preserved and jump returns to the reply", async ({
  page,
}) => {
  await saved(page, false);
  const h = await harness(page);
  h.history = Array.from({ length: 20 }, (_, index) =>
    row(
      index + 1,
      requestId,
      `Older message ${index + 1}\n${"detail ".repeat(30)}`,
    ),
  );
  await page.goto("/");
  await expect(page.getByText(/Older message 20/)).toBeVisible();
  const transcript = page.locator(".transcript");
  await expect
    .poll(() => transcript.evaluate((el) => el.scrollHeight - el.clientHeight))
    .toBeGreaterThan(0);
  await expect
    .poll(() => transcript.evaluate((el) => el.scrollTop))
    .toBeGreaterThan(0);
  await transcript.evaluate((el) => {
    el.scrollTop = Math.min(100, el.scrollHeight - el.clientHeight);
    el.dispatchEvent(new Event("scroll"));
    el.scrollTop = 0;
    el.dispatchEvent(new Event("scroll"));
  });
  await page.getByRole("textbox").fill("What is the latest option?");
  await page.getByRole("textbox").press("Enter");
  await expect(
    page.getByRole("button", { name: "Jump to latest" }),
  ).toBeVisible();
  expect(await transcript.evaluate((el) => el.scrollTop)).toBe(0);
  await page.getByRole("button", { name: "Jump to latest" }).click();
  await expect(
    page.getByRole("button", { name: "Jump to latest" }),
  ).toHaveCount(0);
  await expect
    .poll(() =>
      transcript.evaluate((el) => {
        const answer = el.querySelector(".assistant:last-of-type");
        if (!answer) return false;
        const viewport = el.getBoundingClientRect();
        const bounds = answer.getBoundingClientRect();
        return bounds.top >= viewport.top && bounds.top < viewport.bottom;
      }),
    )
    .toBe(true);
});

test("reduced motion displays a new reply immediately", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await harness(page);
  await page.goto("/");
  await send(page);
  await expect(page.locator(".fast-reveal")).toHaveAttribute(
    "data-revealing",
    "false",
  );
  await expect(
    page.getByText("A real inventory reply", { exact: true }),
  ).toBeVisible();
});
test("double submit is locked; lost response retry uses exact identity", async ({
  page,
}) => {
  const h = await harness(page);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  h.onPost = async (route) => {
    await gate;
    await route.abort();
  };
  await page.goto("/");
  await send(page);
  await expect(page.locator(".optimistic-user .message-text")).toHaveText(
    "Show SUVs",
  );
  await expect(page.locator(".pending")).toHaveCount(0);
  await expect(page.locator(".user")).toHaveCount(1);
  await page.getByRole("textbox").press("Enter");
  await expect(
    page.getByRole("button", { name: "Send", exact: true }),
  ).toBeDisabled();
  await expect.poll(() => h.posts.length).toBe(1);
  release();
  await page.getByRole("button", { name: "Check reply" }).click();
  await expect.poll(() => h.posts.length).toBe(2);
  expect(h.posts[1]).toEqual(h.posts[0]);
  h.onPost = undefined;
  await page.getByRole("button", { name: "Check reply" }).click();
  await expect(
    page.getByText("A real inventory reply", { exact: true }),
  ).toHaveCount(1);
  expect(h.posts[2]).toEqual(h.posts[0]);
});

test("slow accepted reply survives reload, polls once per cadence and completes without another POST", async ({
  page,
}) => {
  const h = await harness(page);
  await page.clock.install();
  h.onPost = (route, body) => {
    h.history = [row(1, body.request_id, body.text, "in_progress")];
    return route.fulfill({
      status: 202,
      json: {
        conversation_id: conversation,
        request_id: body.request_id,
        status: "in_progress",
      },
    });
  };
  await page.goto("/");
  await send(page);
  await expect(page.getByText("Accepted · Reply in progress")).toBeVisible();
  await expect.poll(() => h.polls).toBe(1);
  await page.reload();
  await expect.poll(() => h.polls).toBe(2);
  await expect(page.locator(".user")).toHaveCount(1);
  expect(h.posts).toHaveLength(1);
  await page.setViewportSize({ width: 320, height: 720 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  const body = h.posts[0]!;
  h.history = [
    row(1, body.request_id, body.text),
    row(2, body.request_id, "Finished reply"),
  ];
  await page.clock.fastForward(500);
  await expect(page.getByText("Finished reply", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "New chat" })).toBeEnabled();
  const polls = h.polls;
  await page.clock.fastForward(60_000);
  expect(h.polls).toBe(polls);
  expect(h.posts).toHaveLength(1);
  await expect(page.locator(".user")).toHaveCount(1);
});

test("saved provider timeout explains the cause after reload", async ({
  page,
}) => {
  const h = await harness(page);
  await saved(page, false);
  h.history = [
    {
      ...row(1, requestId, "Show SUVs", "failed"),
      error_code: "provider_timeout",
    },
  ];
  await page.goto("/");
  await expect(
    page.getByText(/Reply failed.*AI service took too long/),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByText(/Reply failed.*AI service took too long/),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
  expect(h.posts).toHaveLength(0);
});
for (const [code, status] of [
  ["conversation_busy", 409],
  ["server_busy", 503],
  ["request_id_conflict", 409],
] as const) {
  test(`${code} retains the request and blocks new sends`, async ({ page }) => {
    const h = await harness(page);
    h.onPost = (route) =>
      route.fulfill({ status, json: { error: { code, message: code } } });
    await page.goto("/");
    await send(page);
    await expect(page.locator(".optimistic-user")).toContainText("Show SUVs");
    await expect(
      page.locator(".optimistic-user .message-status"),
    ).not.toBeEmpty();
    await expect(
      page.getByRole("button", { name: "Check reply" }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "New chat" })).toBeDisabled();
    await page.getByRole("button", { name: "Check reply" }).click();
    await expect.poll(() => h.posts.length).toBe(2);
    expect(h.posts[1]).toEqual(h.posts[0]);
    await expect(
      page.getByRole("button", { name: "Check reply" }),
    ).toBeVisible();
    await expect(page.locator(".assistant")).toHaveCount(0);
  });
}
for (const [status, code] of [
  ["failed", "provider_error"],
  ["failed", "provider_timeout"],
  ["interrupted", "request_interrupted"],
] as const) {
  test(`${code} updates an existing sequence and a deliberate retry gets a new ID`, async ({
    page,
  }) => {
    await saved(page, false);
    const h = await harness(page);
    h.history = [row(1, requestId, "Show SUVs", "in_progress")];
    h.onStatus = (route) => route.abort();
    await page.goto("/");
    await expect(page.getByText("Accepted · Reply in progress")).toBeVisible();
    // Deliberately stale history: the status outcome must take precedence.
    h.onStatus = (route) =>
      route.fulfill({
        json: {
          conversation_id: conversation,
          request_id: requestId,
          status,
          outcome: { error: { code, message: code } },
        },
      });
    await page.getByRole("button", { name: "Check reply" }).click();
    await expect(
      page.getByText(
        status === "failed"
          ? `Reply failed · No reply was saved. ${code === "provider_timeout" ? "The AI service took too long to respond." : "The AI service could not complete your reply."}`
          : "Reply interrupted · No reply was saved",
      ),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "New chat" })).toBeEnabled();
    await page.getByRole("button", { name: "Try again" }).click();
    expect(h.posts).toHaveLength(0);
    h.onStatus = undefined;
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await expect.poll(() => h.posts.length).toBe(1);
    expect(h.posts[0]?.request_id).not.toBe(requestId);
    await expect(
      page.getByText("A real inventory reply", { exact: true }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Try again" })).toHaveCount(
      0,
    );
  });
}
test("validated missing conversation unlocks explicit recovery and preserves editable text", async ({
  page,
}) => {
  await saved(page);
  const h = await harness(page);
  h.onHistory = (route) =>
    route.fulfill({
      status: 404,
      json: { error: { code: "not_found", message: "gone" } },
    });
  await page.goto("/");
  await expect(
    page.getByText(/This conversation is unavailable/),
  ).toBeVisible();
  await page.getByRole("button", { name: "New chat" }).click();
  await expect(page.getByRole("textbox")).toHaveValue("Show SUVs");
  expect(h.posts).toHaveLength(0);
  expect(h.creates).toBe(0);
  expect(
    await page.evaluate((key) => localStorage.getItem(key), storageKey),
  ).toBeNull();
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect.poll(() => h.posts.length).toBe(1);
  expect(h.posts[0]?.request_id).not.toBe(requestId);
});
for (const kind of ["transport", "html404", "malformed404"] as const) {
  test(`${kind} does not establish a missing conversation`, async ({
    page,
  }) => {
    await saved(page);
    const h = await harness(page);
    h.onHistory = (route) =>
      kind === "transport"
        ? route.abort()
        : route.fulfill({
            status: 404,
            contentType: kind === "html404" ? "text/html" : "application/json",
            body: kind === "html404" ? "<html>proxy</html>" : '{"error":"bad"}',
          });
    await page.goto("/");
    await expect(
      page.getByRole("button", { name: "Continue loading" }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "New chat" })).toBeDisabled();
    expect(h.posts).toHaveLength(0);
  });
}
test("ten-page bound, page failure retry, full restore and no truncation", async ({
  page,
}) => {
  await saved(page, false);
  const h = await harness(page);
  let reads = 0;
  let fail = true;
  h.onHistory = (route) => {
    reads++;
    const after = Number(
      new URL(route.request().url()).searchParams.get("after_sequence"),
    );
    if (after === 100 && fail) {
      fail = false;
      return route.abort();
    }
    const items = Array.from({ length: after < 1100 ? 100 : 1 }, (_, i) =>
      row(after + i + 1, requestId, `History ${after + i + 1}`),
    );
    return route.fulfill({
      json: {
        conversation_id: conversation,
        items,
        next_after_sequence: after < 1100 ? after + 100 : null,
      },
    });
  };
  await page.goto("/");
  await page.getByRole("button", { name: "Continue loading" }).click();
  await expect(page.getByText("History 1100", { exact: true })).toBeVisible();
  expect(reads).toBe(12);
  await expect(
    page.getByRole("button", { name: "Send", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Continue loading" }).click();
  await expect(page.getByRole("button", { name: "New chat" })).toBeEnabled();
  expect(await page.locator(".message").count()).toBe(1101);
});
test("malformed success remains uncertain; validation preserves editable draft", async ({
  page,
}) => {
  const h = await harness(page);
  h.onPost = (route) => route.fulfill({ json: { status: "completed" } });
  await page.goto("/");
  await send(page);
  await expect(page.getByRole("button", { name: "Check reply" })).toBeVisible();
  h.onPost = (route) => route.fulfill({ status: 422, json: { detail: [] } });
  await page.getByRole("button", { name: "Check reply" }).click();
  await expect(page.getByRole("textbox")).toHaveValue("Show SUVs");
  await expect(
    page.getByRole("button", { name: "Send", exact: true }),
  ).toBeEnabled();
});
test("storage failure is visible and in-memory sends still work", async ({
  page,
}) => {
  await page.addInitScript(() => {
    Storage.prototype.setItem = () => {
      throw new Error("blocked");
    };
    Storage.prototype.removeItem = () => {
      throw new Error("blocked");
    };
  });
  await harness(page);
  await page.goto("/");
  await send(page);
  await expect(page.getByText(/Browser storage is unavailable/)).toBeVisible();
  await expect(
    page.getByText("A real inventory reply", { exact: true }),
  ).toBeVisible();
});
test("setup failure and missing slug have actionable recovery", async ({
  page,
}) => {
  await page.route("**/api/dealerships", (route) =>
    route.fulfill({ json: { items: [] } }),
  );
  await page.goto("/");
  await expect(page.getByText(/Mia Motors is not configured/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Retry connection" }),
  ).toBeVisible();
});
test("responsive reflow, safe text, keyboard focus, IME and scroll preservation", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const h = await harness(page);
  await saved(page, false);
  h.history = [
    row(1),
    row(
      2,
      requestId,
      "<script>alert(1)</script>\n" +
        "https://example.com/" +
        "long".repeat(200) +
        "\nDetails\n".repeat(80),
    ),
  ];
  await page.setViewportSize({ width: 320, height: 720 });
  await page.goto("/");
  await expect(page.getByText(/<script>alert/)).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("textbox").focus();
  await expect(page.getByRole("textbox")).toBeFocused();
  await page.getByRole("textbox").fill("日本語");
  await page
    .getByRole("textbox")
    .dispatchEvent("keydown", { key: "Enter", isComposing: true });
  expect(h.posts).toHaveLength(0);
  await page.locator(".transcript").evaluate((el) => {
    el.scrollTop = 0;
    el.dispatchEvent(new Event("scroll"));
  });
  await page.getByRole("textbox").press("Enter");
  await expect.poll(() => h.posts.length).toBe(1);
  await expect
    .poll(() => page.locator(".transcript").evaluate((el) => el.scrollTop))
    .toBe(0);
  await page.screenshot({ path: "test-results/mobile.png", fullPage: true });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.screenshot({ path: "test-results/desktop.png", fullPage: true });
  await page.evaluate(() => {
    document.documentElement.style.fontSize = "200%";
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});

test("reload settles saved pending from completed server history without posting", async ({
  page,
}) => {
  await saved(page);
  const h = await harness(page);
  h.history = [row(1), row(2, requestId, "Previously committed reply")];
  await page.goto("/");
  await expect(page.getByText("Previously committed reply")).toBeVisible();
  await expect(page.locator(".fast-reveal")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "New chat" })).toBeEnabled();
  expect(h.posts).toHaveLength(0);
  const stored: unknown = await page.evaluate(
    (key) => JSON.parse(localStorage.getItem(key) ?? "{}") as unknown,
    storageKey,
  );
  expect(stored).toEqual({ conversation });
});

test("unclear internal error reconciles a committed response", async ({
  page,
}) => {
  const h = await harness(page);
  h.onPost = (route, body) => {
    h.history = [
      row(1, body.request_id, body.text),
      row(2, body.request_id, "Committed despite response loss"),
    ];
    return route.fulfill({
      status: 500,
      json: { error: { code: "internal_error", message: "Unavailable" } },
    });
  };
  await page.goto("/");
  await send(page);
  await expect(page.getByText("Committed despite response loss")).toBeVisible();
  await expect(page.getByRole("button", { name: "New chat" })).toBeEnabled();
  await expect(page.getByRole("status")).toContainText("Reply saved.");
  expect(h.posts).toHaveLength(1);
});

test("lost creation response keeps editable text and makes no message request", async ({
  page,
}) => {
  const h = await harness(page);
  await page.route("**/api/dealerships/*/conversations", (route) =>
    route.abort(),
  );
  await page.goto("/");
  await send(page);
  await expect(page.getByRole("status")).toContainText(
    "creation was unconfirmed",
  );
  await expect(page.getByRole("textbox")).toHaveValue("Show SUVs");
  await expect(
    page.getByRole("button", { name: "Send", exact: true }),
  ).toBeEnabled();
  expect(h.posts).toHaveLength(0);
});

test("nonadvancing history cursor is rejected", async ({ page }) => {
  await saved(page, false);
  const h = await harness(page);
  h.onHistory = (route) =>
    route.fulfill({
      json: {
        conversation_id: conversation,
        items: [],
        next_after_sequence: 0,
      },
    });
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Continue loading" }),
  ).toBeVisible();
  await expect(page.getByRole("textbox")).not.toBeEditable();
  expect(h.posts).toHaveLength(0);
});

test("keyboard navigation and rendered color contrast", async ({ page }) => {
  await harness(page);
  await page.goto("/");
  await expect(page.getByRole("button", { name: "New chat" })).toBeEnabled();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "New chat" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("region", { name: "Conversation" }),
  ).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("textbox")).toBeFocused();
  const ratios = await page.evaluate(() => {
    const style = getComputedStyle(document.documentElement);
    const luminance = (token: string) => {
      const hex = style.getPropertyValue(token).trim().slice(1);
      const channels = [0, 2, 4]
        .map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
        .map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
      return (
        (channels[0] ?? 0) * 0.2126 +
        (channels[1] ?? 0) * 0.7152 +
        (channels[2] ?? 0) * 0.0722
      );
    };
    return [
      ["--aa-text", "--aa-canvas"],
      ["--aa-text", "--aa-user-surface"],
      ["--aa-text-muted", "--aa-canvas"],
      ["--aa-on-action", "--aa-action"],
      ["--aa-chrome-text", "--aa-chrome"],
      ["--aa-warning-text", "--aa-warning-surface"],
      ["--aa-control-border", "--aa-surface"],
    ].map(([a, b]) => {
      const x = luminance(a ?? ""),
        y = luminance(b ?? "");
      return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
    });
  });
  ratios
    .slice(0, -1)
    .forEach((ratio) => expect(ratio).toBeGreaterThanOrEqual(4.5));
  expect(ratios.at(-1)).toBeGreaterThanOrEqual(3);
  expect(
    await page
      .getByRole("textbox")
      .evaluate((el) => getComputedStyle(el).outlineStyle),
  ).not.toBe("none");
});

test("lost creation response preserves identity through reload and new chat replaces it", async ({
  page,
}) => {
  const h = await harness(page);
  const identities: string[] = [];
  h.onCreate = async (route) => {
    const body = route.request().postDataJSON() as { creation_id: string };
    identities.push(body.creation_id);
    if (identities.length === 1) return route.abort("failed");
    return route.fulfill({ status: 201, json: { id: conversation } });
  };
  await page.goto("/");
  await send(page);
  await expect(
    page.getByText(/Conversation creation was unconfirmed/),
  ).toBeVisible();
  expect(h.posts).toHaveLength(0);
  await page.reload();
  await send(page);
  await expect(
    page.getByText("A real inventory reply", { exact: true }),
  ).toBeVisible();
  expect(identities[0]).toMatch(/^[0-9a-f-]{36}$/);
  expect(identities[1]).toBe(identities[0]);
  await page.getByRole("button", { name: "New chat" }).click();
  await send(page);
  await expect.poll(() => identities.length).toBe(3);
  expect(identities[2]).not.toBe(identities[0]);
});

test("polling budget ends with explicit Check reply and keeps the original ID", async ({
  page,
}) => {
  const h = await harness(page);
  await saved(page);
  await page.clock.install();
  h.history = [row(1, requestId, "Show SUVs", "in_progress")];
  await page.goto("/");
  for (let count = 1; count < 20; count++) {
    await expect.poll(() => h.polls).toBe(count);
    // Wait for the response handler to install its next bounded delay.
    await page.clock.runFor(50);
    await page.clock.fastForward(Math.min(500 * 2 ** (count - 1), 5000));
  }
  await expect(page.getByRole("button", { name: "Check reply" })).toBeVisible();
  expect(h.polls).toBe(20);
  await page.clock.fastForward(60_000);
  expect(h.polls).toBe(20);
  expect(h.posts).toHaveLength(0);
  h.history = [row(1), row(2, requestId, "Recovered reply")];
  await page.getByRole("button", { name: "Check reply" }).click();
  await expect(
    page.getByText("Recovered reply", { exact: true }),
  ).toBeVisible();
  expect(h.posts).toHaveLength(0);
});

test("malformed terminal status stays recoverable without a fabricated reply", async ({
  page,
}) => {
  const h = await harness(page);
  await saved(page);
  h.history = [row(1, requestId, "Show SUVs", "in_progress")];
  h.onStatus = (route) =>
    route.fulfill({
      json: {
        conversation_id: conversation,
        request_id: requestId,
        status: "completed",
        outcome: { assistant_message: "invented" },
      },
    });
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Check reply" })).toBeVisible();
  await expect(page.locator(".assistant")).toHaveCount(0);
  expect(h.posts).toHaveLength(0);
  h.onStatus = undefined;
  h.history = [row(1), row(2, requestId, "Actual reply")];
  await page.getByRole("button", { name: "Check reply" }).click();
  await expect(page.getByText("Actual reply", { exact: true })).toBeVisible();
});

test("a late poll cannot restore a conversation after the view changes", async ({
  page,
}) => {
  const h = await harness(page);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  h.onPost = (route, body) => {
    h.history = [row(1, body.request_id, body.text, "in_progress")];
    return route.fulfill({
      status: 202,
      json: {
        conversation_id: conversation,
        request_id: body.request_id,
        status: "in_progress",
      },
    });
  };
  h.onHistory = (route) =>
    route.fulfill({
      status: 404,
      json: {
        error: { code: "not_found", message: "Conversation unavailable" },
      },
    });
  h.onStatus = async (route) => {
    await gate;
    const body = h.posts[0]!;
    await route.fulfill({
      json: {
        conversation_id: conversation,
        request_id: body.request_id,
        status: "completed",
        outcome: {
          conversation_id: conversation,
          request_id: body.request_id,
          status: "completed",
          user_message: row(1, body.request_id, body.text),
          assistant_message: row(2, body.request_id, "Old reply"),
        },
      },
    });
  };
  try {
    await page.goto("/");
    await send(page);
    await expect.poll(() => h.polls).toBe(1);
    await page.getByRole("button", { name: "New chat" }).click();
  } finally {
    release();
  }
  await expect(page.getByRole("textbox")).toHaveValue("Show SUVs");
  await expect(page.locator(".assistant")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Send", exact: true }),
  ).toBeEnabled();
});
