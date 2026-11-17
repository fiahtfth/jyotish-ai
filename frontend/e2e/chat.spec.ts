import { test, expect } from "@playwright/test";

const message = (id: number, role: string, content: string) => ({
  id, role, content, kind: "text", meta: {}, created_at: "2026-11-17T12:00:00",
});

test.beforeEach(async ({ page }, testInfo) => {
  if (!testInfo.title.startsWith("signup")) {
    await page.addInitScript(() => localStorage.setItem("jyotish_token", "test-token"));
  }
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

test("existing accounts accept service terms once, without an AI toggle", async ({ page }) => {
  await page.route("**/api/auth/me", route => route.fulfill({ json: {
    id: 1, email: "test@example.com", display_name: "Tester", has_profile: true,
    llm_consent: false, email_verified: true, ai_terms_required: true, terms_version: null,
  } }));
  await page.route("**/api/chat/history", route => route.fulfill({ json: [message(1, "assistant", "Welcome")] }));
  let accepted = false;
  await page.route("**/api/auth/terms", route => {
    accepted = route.request().postDataJSON().terms_accepted === true;
    return route.fulfill({ json: { llm_consent: true, ai_terms_required: false, terms_version: "2026-11-17" } });
  });
  await page.goto("/chat");
  const panel = page.getByRole("region", { name: "Updated service terms" });
  await expect(panel).toBeVisible();
  await expect(page.getByPlaceholder(/ask anything/i)).toBeDisabled();
  await expect(panel.getByRole("button", { name: "Accept and continue" })).toBeDisabled();
  await panel.getByRole("checkbox", { name: /terms and conditions/i }).check();
  await panel.getByRole("button", { name: "Accept and continue" }).click();
  await expect(panel).toHaveCount(0);
  expect(accepted).toBe(true);
  await expect(page.getByPlaceholder(/ask anything/i)).toBeEnabled();
  await page.locator("header button.rounded-full").click();
  await expect(page.getByRole("button", { name: /external AI/i })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "terms and conditions", exact: true })).toBeVisible();
});

test("signup includes AI processing in one required terms agreement", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "Create account", exact: true }).first().click();
  await expect(page.getByRole("checkbox")).toHaveCount(1);
  await expect(page.getByText(/sends your chart summary and recent messages/i)).toBeVisible();
  await expect(page.getByRole("link", { name: "terms and conditions" })).toHaveAttribute("href", "/terms");
  await expect(page.locator("form").getByRole("button", { name: "Create account", exact: true }).last()).toBeDisabled();
});
