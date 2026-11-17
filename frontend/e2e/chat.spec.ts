import { test, expect } from "@playwright/test";

const message = (id: number, role: string, content: string) => ({
  id, role, content, kind: "text", meta: {}, created_at: "2026-11-17T12:00:00",
});

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("jyotish_token", "test-token"));
  await page.route("**/api/auth/me", route => route.fulfill({ json: {
    id: 1, email: "test@example.com", display_name: "Tester", has_profile: true,
    llm_consent: false, email_verified: true,
  } }));
});

test("shows a history failure and offers recovery", async ({ page }) => {
  await page.route("**/api/chat/history", route => route.fulfill({ status: 503, json: { detail: "Chat temporarily unavailable" } }));
  await page.goto("/chat");
  await expect(page.getByRole("alert").filter({ hasText: "Chat temporarily unavailable" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Reload conversation" })).toBeVisible();
  await expect(page.getByPlaceholder(/ask anything/i)).toBeDisabled();
});

test("a broken stream never resends the turn", async ({ page }) => {
  await page.route("**/api/chat/history", route => route.fulfill({ json: [message(1, "assistant", "Welcome")] }));
  let streamCalls = 0;
  let sendCalls = 0;
  await page.route("**/api/chat/stream", route => { streamCalls++; return route.abort("failed"); });
  await page.route("**/api/chat/send", route => { sendCalls++; return route.fulfill({ json: [] }); });
  await page.goto("/chat");
  await expect(page.getByText("Welcome", { exact: true })).toBeVisible();
  await page.getByPlaceholder(/ask anything/i).fill("Tell me about my Moon");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Reload conversation" })).toBeVisible();
  expect(streamCalls).toBe(1);
  expect(sendCalls).toBe(0);
  await expect(page.getByText("Tell me about my Moon", { exact: true })).toHaveCount(1);
});

test("focus does not replace an active turn and final messages appear once", async ({ page }) => {
  let histories = 0;
  await page.route("**/api/chat/history", route => { histories++; return route.fulfill({ json: [message(1, "assistant", "Welcome")] }); });
  let release!: () => void;
  const ready = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/chat/stream", async route => {
    await ready;
    await route.fulfill({ contentType: "text/event-stream", body:
      `data: ${JSON.stringify({ type: "delta", text: "Your Moon" })}\n\n` +
      `data: ${JSON.stringify({ type: "done", messages: [message(2, "user", "My Moon?"), message(3, "assistant", "Your Moon is in Sagittarius.")] })}\n\n`,
    });
  });
  await page.goto("/chat");
  await expect(page.getByText("Welcome", { exact: true })).toBeVisible();
  await page.getByPlaceholder(/ask anything/i).fill("My Moon?");
  await page.keyboard.press("Enter");
  await expect(page.getByText("My Moon?", { exact: true })).toHaveCount(1);
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  expect(histories).toBe(1);
  release();
  await expect(page.getByText("Your Moon is in Sagittarius.", { exact: true })).toBeVisible();
  await expect(page.getByText("My Moon?", { exact: true })).toHaveCount(1);
});
