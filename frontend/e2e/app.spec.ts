import { test, expect } from "@playwright/test";

const email = `e2e${Date.now()}@example.com`;
const password = "E2e-pass-12345";

test.describe.configure({ mode: "serial" });

test("register, birth details, calibration, chat, sign out/in, privacy, delete", async ({ page }) => {
  const browserErrors: string[] = [];
  page.on("pageerror", error => browserErrors.push(error.message));
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

  // Confirm the resolved historical offset before entering the chat.
  await expect(page.getByText("UTC+05:30", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /continue with this offset/i }).click();

  // Chat: opening message + calibration
  await page.waitForURL(/\/chat/);
  const no = page.getByRole("button", { name: "No, that didn't happen" });
  const continueReading = page.getByRole("button", { name: "Continue with the reading" });
  await expect(continueReading).toBeVisible();
  for (let i = 0; i < 3; i++) {
    await Promise.all([
      page.waitForResponse(r => r.url().endsWith("/api/chat/stream") && r.ok()),
      no.click(),
    ]);
    await expect(page.getByText("No, that didn't happen", { exact: true }).and(page.locator(".chat-message"))).toHaveCount(i + 1);
    await expect(page.getByPlaceholder(/ask anything/i)).toBeEnabled();
  }
  await expect(page.getByText(/predictions may be less accurate/)).toBeVisible();
  // A typed question must work immediately, without pressing Continue or editing the time.
  const box = page.getByPlaceholder(/ask anything/i);
  await box.fill("Will I change jobs next year?");
  await box.press("Enter");
  await expect(page.locator(".chat-message").last()).toContainText(/for a job change in/i);
  await expect(continueReading).toHaveCount(0);

  await box.fill("What about July 2027?");
  await box.press("Enter");
  await expect(page.locator(".chat-message").last()).toContainText(/a job change in July 2027/i);
  await box.fill("Actually, I meant a promotion at my current company.");
  await box.press("Enter");
  await expect(page.locator(".chat-message").last()).toContainText(/promotion in July 2027/i);
  await box.fill("I work as a school principal.");
  await box.press("Enter");
  await expect(page.getByText("I work as a school principal.", { exact: true })).toBeVisible();
  await expect(box).toBeEnabled();

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
  await box.fill("What do you remember about me?");
  await box.press("Enter");
  await expect(page.locator(".chat-message").last()).toContainText("I work as a school principal.");

  await page.locator("header button.rounded-full").click();
  await page.getByRole("link", { name: "Chart dashboard" }).click();
  await expect(page.getByRole("heading", { name: "Chart dashboard" })).toBeVisible();
  await page.getByLabel("Divisional chart").selectOption("D9");
  await expect(page.getByText(/Parashari Navamsha/)).toBeVisible();
  await page.getByRole("button", { name: "Timeline" }).click();
  await expect(page.getByRole("heading", { name: "Yogini" })).toBeVisible();
  await page.getByRole("button", { name: "Sensitivity" }).click();
  await expect(page.getByText("Moon pada", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Ashtakavarga" }).click();
  await expect(page.getByText("SAV", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Transits" }).click();
  await page.getByLabel("From (UTC)").fill("2027-01-01");
  await page.getByLabel("Until (UTC)").fill("2027-04-01");
  await page.getByRole("button", { name: "Find transitions" }).click();
  await expect(page.getByRole("heading", { name: "Sade Sati phases" })).toBeVisible();
  await page.getByRole("button", { name: "KP", exact: true }).click();
  await page.getByRole("button", { name: "Calculate KP chart" }).click();
  await expect(page.getByText(/Swiss Krishnamurti.*Placidus/)).toBeVisible();
  await page.getByRole("button", { name: "Paste degrees" }).click();
  await page.getByLabel("Ayanamsa").selectOption("LAHIRI");
  await page.getByLabel("Original degree table").fill("Moon 3°20′00″ Ari");
  await page.getByRole("button", { name: "Check pasted degrees" }).click();
  await expect(page.getByText("Aries or Taurus", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Coverage", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Calculation coverage" })).toBeVisible();
  await expect(page.getByText(/60 intents/)).toBeVisible();

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
  expect(browserErrors).toEqual([]);
});
