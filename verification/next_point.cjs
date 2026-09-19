const assert = require("node:assert/strict");
const { chromium } = require("C:/Users/Senthil/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("http://127.0.0.1:3000/?api=/api", { waitUntil: "networkidle" });
  await page.waitForSelector("#svgHost svg");
  await page.locator("#startSearch").click();
  await page.getByRole("button", { name: /Entrance 1/ }).first().click();
  await page.locator("#destinationSearch").fill("234");
  await page.locator("#destinationSuggestions .suggestion-item").first().click();
  await page.locator("#navigateBtn").click();
  await page.waitForSelector("body.route-active #stepBar:not([hidden])");
  const before = await page.locator("#dockProgressPercent").innerText();
  await page.locator("#confirmNextBtn").click();
  await page.waitForFunction((previous) => document.querySelector("#dockProgressPercent")?.textContent !== previous, before);
  const after = await page.locator("#dockProgressPercent").innerText();
  assert.notEqual(before, after, "Next point must advance route progress");
  assert.deepEqual(errors, [], `Browser errors: ${errors.join(" | ")}`);
  console.log(`Next point verified: ${before} -> ${after}; browser errors=0.`);
  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
