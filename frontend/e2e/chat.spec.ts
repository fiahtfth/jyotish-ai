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
  await expect(page.getByText(/recent messages and relevant details remembered/i)).toBeVisible();
  await expect(page.getByRole("link", { name: "terms and conditions" })).toHaveAttribute("href", "/terms");
  await expect(page.locator("form").getByRole("button", { name: "Create account", exact: true }).last()).toBeDisabled();
});

test("scorecard separates abstentions and records an event outside the window as a miss", async ({ page }) => {
  await page.route("**/api/chat/history", route => route.fulfill({ json: [message(1, "assistant", "Welcome")] }));
  let reported = false;
  const record = { id: 21, domain: "career", question: "Will I get a promotion?", forecast: "event_indicated",
    success_criteria: "A formal promotion takes effect within 2020-02-01 to 2020-02-28.",
    window_start: "2020-02-01", window_end: "2020-02-28", convergence: "3/4 Strong rule agreement",
    created_at: "2020-01-01", outcome_at: null };
  await page.route("**/api/predictions", route => route.fulfill({ json: {
    predictions: [{ ...record, outcome: reported ? "outside_window" : null }],
    aggregate: { total: 1, happened: 0, partly: 0, did_not: 0, unsure: 0, pending: reported ? 0 : 1 },
    scorecard: { total_analyses: 2, issued_forecasts: 1, abstentions: 1, prospective_forecasts: 1,
      matured: 1, scored: reported ? 1 : 0, hits: 0, misses: reported ? 1 : 0, partial: 0, unresolved: reported ? 0 : 1 },
  } }));
  await page.route("**/api/predictions/21/outcome", route => {
    expect(route.request().postDataJSON()).toEqual({ outcome: "happened", event_date: "2020-03-01" });
    reported = true;
    return route.fulfill({ json: { id: 21, outcome: "outside_window" } });
  });
  await page.goto("/chat");
  await expect(page.getByText("Welcome", { exact: true })).toBeVisible();
  await page.locator("header button.rounded-full").click();
  await page.getByRole("button", { name: /my predictions/i }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("region", { name: "Prediction scorecard" })).toBeVisible();
  await expect(dialog.getByText(record.success_criteria)).toBeVisible();
  await dialog.getByLabel("Report the outcome").selectOption("happened");
  await expect(dialog.getByRole("button", { name: "Save outcome" })).toBeDisabled();
  await dialog.getByLabel("Date the event occurred").fill("2020-03-01");
  await dialog.getByRole("button", { name: "Save outcome" }).click();
  await expect(dialog.locator("span").filter({ hasText: /^Outside the window$/ })).toBeVisible();
  expect(reported).toBe(true);
});


test("chat hides rule-agreement footers while preserving the reading", async ({ page }) => {
  await page.route("**/api/chat/history", route => route.fulfill({ json: [{
    ...message(1, "assistant", "Your chart highlights professional responsibilities."),
    meta: { analysis: { convergence: "2/4 Mixed or limited rule agreement" } },
  }] }));
  await page.goto("/chat");
  await expect(page.getByText("Your chart highlights professional responsibilities.", { exact: true })).toBeVisible();
  await expect(page.getByText("2/4 Mixed or limited rule agreement", { exact: true })).toHaveCount(0);
});


for (const width of [320, 390, 1024]) {
  test(`long chat replies wrap without horizontal overflow at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    const paragraph = "Donate half a kilogram of black lentils to a senior citizen home or to the poor on Saturday whenever possible.";
    const text = "1. Saturn\n" + paragraph.replaceAll(" ", "\u00a0") + "\n\n2. Rahu\n" + "OmRaamRaaHumHreemShreemNamah".repeat(12) + "\n" + paragraph;
    await page.route("**/api/chat/history", route => route.fulfill({ json: [
      message(1, "assistant", text), message(2, "user", "https://example.com/" + "long-path".repeat(40)),
      { ...message(3, "assistant", text), kind: "options", meta: { options: ["Yes", "No"] } },
    ] }));
    await page.goto("/chat");
    const bubbles = page.locator(".chat-message");
    await expect(bubbles).toHaveCount(3);
    for (const bubble of await bubbles.all()) {
      const size = await bubble.evaluate(node => {
        const box = node.getBoundingClientRect();
        return { client: node.clientWidth, scroll: node.scrollWidth, left: box.left, right: box.right };
      });
      expect(size.scroll).toBeLessThanOrEqual(size.client + 1);
      expect(size.left).toBeGreaterThanOrEqual(0);
      expect(size.right).toBeLessThanOrEqual(width);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await expect(bubbles.first()).toHaveText(text);
  });
}

test("forecast evidence tables fit a mobile chat bubble", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 });
  const columns = ["Point", "D1", "D2", "D6", "D7", "D9", "D10", "D12", "D24", "D60"];
  const tables = [{ title: "Lahiri positions", columns, rows: [columns.map(() => "Sagittarius 20.0010°")] }];
  const reading = { ...message(5, "assistant", "Career reading"), meta: { analysis: {
    decision: { event: { event_type: "promotion" } }, classical: { tables, note: "Sampled on one date." },
  } } };
  await page.route("**/api/chat/history", route => route.fulfill({ json: [reading] }));
  await page.goto("/chat");
  await expect(page.getByRole("table", { name: "Lahiri positions" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
  await page.getByText("Chart calculations and timing evidence").click();
  await expect(page.getByText("Career reading")).toBeVisible();
  await expect(page.getByRole("table")).toHaveCount(0);
});


test("career matching keeps the recommendation in the chat and sources in expandable evidence", async ({ page }) => {
  await page.route("**/api/chat/history", route => route.fulfill({
    json: [{
      ...message(1, "assistant", "BI analyst is the strongest fit from your shortlist."),
      meta: {
        career_result: {
          leader: "BI analyst",
          roles: [{ title: "BI analyst", code: "15-2051.01", matched: ["SQL"], preferred: [],
            blockers: [], unknown: [] }],
        },
        career_sources: { attribution: "Adapted from the O*NET® database", database: "https://www.onetcenter.org/database.html" },
      },
    }],
  }));
  await page.goto("/chat");
  await expect(page.getByText("BI analyst is the strongest fit from your shortlist.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Occupation profile" })).toBeHidden();
  await page.getByText("Career comparison evidence").click();
  await expect(page.getByText("Experience mentioned · SQL")).toBeVisible();
  await expect(page.getByRole("link", { name: "Occupation profile" })).toHaveAttribute("href", /15-2051\.01$/);
});
