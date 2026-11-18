import { test, expect } from "@playwright/test";

const email = `e2e${Date.now()}@example.com`;
const password = "E2e-pass-12345";

test.describe.configure({ mode: "serial" });

test("register, birth details, calibration, chat, sign out/in, privacy, delete", async ({ page }) => {
  // Register
  await page.goto("/login");
  await page.getByRole("button", { name: /create account/i }).first().click();
  await page.getByPlaceholder(/your name/i).fill("E2E Tester");
  await page.getByPlaceholder(/email/i).fill(email);
  await page.getByPlaceholder(/password/i).fill(password);
  await page.getByRole("checkbox", { name: /privacy policy/i }).check();
  await page.locator("form").getByRole("button", { name: /create account/i }).last().click();

  // Birth details (defaults for date/time are fine); pick Chennai
  await page.waitForURL(/\/birth/);
  await page.getByPlaceholder(/birth place|city/i).fill("Chennai");
  await page.getByRole("button", { name: /^Chennai/ }).first().click();
  await page.locator("form").getByRole("button", { name: /continue/i }).click();

  // Chat: opening message + calibration
  await page.waitForURL(/\/chat/);
  const yes = page.getByRole("button", { name: /yes, that happened/i });
  await expect(yes.first()).toBeVisible({ timeout: 30_000 });
  for (let i = 0; i < 3; i++) {
    await yes.first().click();
    // next calibration question (or end of calibration) arrives
    await page.waitForTimeout(500);
    if (i < 2) await expect(yes.first()).toBeVisible({ timeout: 30_000 });
  }

  // Ask a question, expect a reply (offline responder)
  const box = page.getByPlaceholder(/ask anything/i);
  await expect(box).toBeVisible();
  await box.fill("What does my chart say about career?");
  const before = await page.locator("div.whitespace-pre-wrap").count();
  await page.keyboard.press("Enter");
  await expect(async () => {
    expect(await page.locator("div.whitespace-pre-wrap").count()).toBeGreaterThan(before + 1);
  }).toPass({ timeout: 45_000 });

  // Sign out / in
  await page.getByRole("button", { name: /sign out/i }).or(
    page.locator("header button.rounded-full")).first().click();
  if (await page.getByRole("button", { name: /sign out/i }).isVisible()) {
    await page.getByRole("button", { name: /sign out/i }).click();
  }
  await page.waitForURL(/\/login/);
  await page.getByPlaceholder(/email/i).fill(email);
  await page.getByPlaceholder(/password/i).fill(password);
  await page.locator("form").getByRole("button", { name: /sign in/i }).last().click();
  await page.waitForURL(/\/chat/);

  // Privacy page reachable
  const res = await page.goto("/privacy");
  expect(res?.ok()).toBeTruthy();
  await expect(page.getByRole("heading").first()).toBeVisible();

  // Delete account via menu (confirm dialog)
  await page.goto("/chat");
  page.once("dialog", d => d.accept());
  await page.locator("header button.rounded-full").click();
  await page.getByRole("button", { name: /delete account/i }).click();
  await page.waitForURL(/\/login/);
});
