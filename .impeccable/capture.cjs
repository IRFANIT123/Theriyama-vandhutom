const { chromium } = require("C:/Users/Senthil/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");

async function capture(browser, name, viewport, fullPage, activeRoute = false, mapMode = "25d") {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
  const page = await context.newPage();
  const issues = [];
  page.on("console", (message) => {
    if (message.type() === "error") issues.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => issues.push(`page: ${error.message}`));
  await page.goto("http://127.0.0.1:3000/?api=/api", { waitUntil: "networkidle" });
  try {
    await page.waitForSelector("#svgHost svg", { state: "attached", timeout: 15000 });
  } catch (error) {
    console.log(`startup issues: ${JSON.stringify(issues)}`);
    console.log((await page.locator("body").innerText()).slice(0, 2000));
    throw error;
  }
  if (mapMode === "2d") {
    await page.locator('[data-map-mode="2d"]').click();
    await page.waitForSelector("#svgHost svg.cn-map-2d", { timeout: 15000 });
  }
  if (activeRoute) {
    await page.locator("#startSearch").click();
    await page.getByRole("button", { name: /Entrance 1/ }).first().click();
    await page.locator("#destinationSearch").fill("234");
    await page.locator("#destinationSuggestions .suggestion-item").first().click();
    await page.locator("#navigateBtn").click();
    await page.waitForSelector("body.route-active #stepBar:not([hidden])", { timeout: 15000 });
    await page.waitForSelector("#toast:not(.show)", { timeout: 5000 });
  }
  const geometry = await page.evaluate(() => {
    const box = (selector) => {
      const element = document.querySelector(selector);
      if (!element) return null;
      const rect = element.getBoundingClientRect();
      return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
    };
    return {
      scrollHeight: document.documentElement.scrollHeight,
      mapPanel: box(".map-panel"),
      mapViewport: box(".map-viewport"),
      svgHost: box("#svgHost"),
      svg: box("#svgHost svg")
    };
  });
  await page.screenshot({ path: `.impeccable/review/${name}.png`, fullPage });
  console.log(`${name}: ${await page.title()} · ${viewport.width}x${viewport.height} · ${issues.length} errors · ${JSON.stringify(geometry)}`);
  for (const issue of issues) console.log(`  ${issue}`);
  if (name === "desktop") {
    for (const floorId of ["F1", "F2", "F3", "F4", "F5", "F6", "F7", "G"]) {
      await page.locator(`[data-floor="${floorId}"]`).first().click();
      await page.waitForSelector(`#svgHost svg[data-floor="${floorId}"]`, { state: "attached", timeout: 15000 });
      if (floorId === "F2" || floorId === "F7") {
        await page.screenshot({ path: `.impeccable/review/floor-${floorId.toLowerCase()}.png`, fullPage: false });
      }
    }
    console.log(`desktop floors: G–F7 projection sweep complete · ${issues.length} errors`);
  }
  if (name === "desktop-active") {
    const before = await page.locator("#dockProgressPercent").innerText();
    await page.locator("#confirmNextBtn").click();
    await page.waitForFunction(previous => document.querySelector("#dockProgressPercent")?.textContent !== previous, before);
    const after = await page.locator("#dockProgressPercent").innerText();
    console.log(`desktop next-point: ${before} → ${after}`);
  }
  await context.close();
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  await capture(browser, "desktop", { width: 1440, height: 900 }, false);
  await capture(browser, "desktop-2d", { width: 1440, height: 900 }, false, false, "2d");
  await capture(browser, "mobile", { width: 390, height: 844 }, true);
  await capture(browser, "desktop-active", { width: 1440, height: 900 }, false, true);
  await capture(browser, "mobile-active", { width: 390, height: 844 }, true, true);
  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
