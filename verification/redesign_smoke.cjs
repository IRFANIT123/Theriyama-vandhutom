const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("C:/Users/Senthil/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");

const baseUrl = process.env.NAVORA_URL || "http://127.0.0.1:3001/?api=/api";
const routeOrigin = new URL(baseUrl).origin;
const outputDir = path.join(__dirname, "output");

(async () => {
  fs.mkdirSync(outputDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const errors = [];
    page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
    page.on("pageerror", error => errors.push(error.message));

    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.waitForSelector("#startSearch:not([disabled])");
    assert.match(await page.locator("#apiPill").getAttribute("class"), /online/);
    assert.equal(await page.locator("#floorOverviewButtons button").count(), 8);
    assert.equal(await page.locator("#svgHost svg").count(), 1);
    assert.equal(await page.locator(".brand-name").innerText(), "Navora");
    assert.equal((await page.locator("#navigateBtn span").first().innerText()).toLowerCase(), "start navigation");
    assert.equal(await page.locator('button[data-map-mode="2d"]').getAttribute("aria-pressed"), "true");
    assert.match(await page.locator("#mapViewport").evaluate(element => getComputedStyle(element).backgroundImage), /gradient/i);
    assert.match(await page.locator(".topbar").evaluate(element => getComputedStyle(element).backgroundImage), /gradient/i);
    assert.match(await page.locator(".planner-panel").evaluate(element => getComputedStyle(element).backgroundImage), /gradient/i);
    const roomCodeWeight = Number(await page.locator("#campusnav-map-labels .cn-room-code").first()
      .evaluate(element => getComputedStyle(element).fontWeight));
    assert(roomCodeWeight >= 800, `Room code weight was ${roomCodeWeight}`);

    const routeResponse = await page.request.get(
      routeOrigin + "/api/route?start_floor=F6&start=635&destination_floor=G&destination=G31&mode=stairs"
    );
    assert.equal(routeResponse.status(), 200);
    const directRoute = await routeResponse.json();
    assert.deepEqual(directRoute.floors, ["F6", "G"]);

    await page.locator("#startSearch").fill("G41");
    await page.locator("#startSuggestions .suggestion-item").first().click();
    await page.locator("#destinationSearch").fill("421");
    await page.locator("#destinationSuggestions .suggestion-item").first().click();
    await page.locator("#navigateBtn").click();
    await page.waitForSelector("body.route-active #stepBar:not([hidden])");
    assert(await page.locator("#svgHost svg .cn-route-line").count() >= 1);
    assert.equal(
      await page.locator("#svgHost svg .cn-route-line").first().evaluate(element => getComputedStyle(element).stroke),
      "rgb(255, 67, 94)"
    );
    assert(await page.locator("#svgHost svg .cn-next-pulse").count() >= 1);
    assert.match(await page.locator("#dockPointCounter").innerText(), /of/);
    assert.equal(await page.locator("#confirmNextBtn").isEnabled(), true);
    assert.equal(await page.locator(".step-actions #previousCheckpointBtn").count(), 1);
    assert.equal(await page.locator("#previousCheckpointBtn").isDisabled(), true);

    const firstProgress = await page.locator("#dockPointCounter").innerText();
    await page.locator("#confirmNextBtn").click();
    await page.waitForFunction(previous => document.querySelector("#dockPointCounter")?.textContent !== previous, firstProgress);
    assert.equal(await page.locator("#previousCheckpointBtn").isEnabled(), true);
    await page.locator("#previousCheckpointBtn").click();
    await page.waitForFunction(previous => document.querySelector("#dockPointCounter")?.textContent === previous, firstProgress);
    assert.equal(await page.locator("#previousCheckpointBtn").isDisabled(), true);

    await page.screenshot({
      path: path.join(outputDir, "navora-polished.jpg"),
      fullPage: true,
      type: "jpeg",
      quality: 68,
    });
    assert.deepEqual(errors, [], "Browser errors: " + errors.join(" | "));
    console.log("Redesigned Navora passed real-data boot, floor rail, search, routing, route overlay, progress, and direct-stair checks.");
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
