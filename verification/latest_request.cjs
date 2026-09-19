const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("C:/Users/Senthil/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");

const baseUrl = "http://127.0.0.1:3000/?api=/api";
const outputDir = path.join(__dirname, "output");

(async () => {
  fs.mkdirSync(outputDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
  page.on("pageerror", error => errors.push(error.message));

  const response = await page.request.get(
    "http://127.0.0.1:3000/api/route?start_floor=F6&start=635&destination_floor=G&destination=G31&mode=stairs"
  );
  assert.equal(response.status(), 200);
  const route = await response.json();
  assert.deepEqual(route.floors, ["F6", "G"], "cross-floor stair route must skip intermediate floors");
  assert.deepEqual(Object.keys(route.floor_routes), ["F6", "G"]);
  assert(route.instructions.some(item => item.text === "Take the stairs from F6 to G"));

  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.waitForSelector("#startSearch:not([disabled])");
  await page.locator("#startSearch").fill("635");
  await page.locator("#startSuggestions .suggestion-item", { hasText: "635" }).first().click();
  await page.locator("#destinationSearch").fill("G31");
  await page.locator("#destinationSuggestions .suggestion-item", { hasText: "G31" }).first().click();
  await page.locator("#navigateBtn").click();
  await page.waitForSelector("body.route-active #stepBar:not([hidden])");

  const startLabel = page.locator('[data-map-label].cn-selected-start-label[aria-label^="635 ·"]');
  await startLabel.waitFor();
  assert.equal(await startLabel.evaluate(node => getComputedStyle(node).visibility), "visible");

  await page.locator('[data-floor="G"]').first().click();
  await page.waitForSelector('#svgHost svg[data-floor="G"]');
  const destinationLabel = page.locator("[data-map-label].cn-selected-destination-label").first();
  await destinationLabel.waitFor();
  assert.match(await destinationLabel.getAttribute("aria-label"), /^G-?31 ·/);
  assert.equal(await destinationLabel.evaluate(node => getComputedStyle(node).visibility), "visible");

  await page.locator("#fitBtn").click();
  const fitHeight = await destinationLabel.evaluate(node => node.getBoundingClientRect().height);
  await page.locator("#zoomInBtn").click();
  await page.locator("#zoomInBtn").click();
  const zoomHeight = await destinationLabel.evaluate(node => node.getBoundingClientRect().height);
  assert(Math.abs(fitHeight - zoomHeight) < 2, "G31 label must keep a stable screen font size while zooming");

  const rotationMs = await page.evaluate(() => new Promise(resolve => {
    const started = performance.now();
    document.querySelector("#rotateMapBtn").click();
    requestAnimationFrame(() => resolve(performance.now() - started));
  }));
  assert(rotationMs < 100, "180 degree rotation must complete in one animation frame");
  assert.equal(await page.locator("#rotateMapBtn").getAttribute("aria-pressed"), "true");
  assert.match(await page.locator("#campusnav-user-rotation").getAttribute("transform"), /rotate\(180/);

  const classroom = page.locator(".cn-classroom-detail").first();
  assert.equal(await classroom.locator(".cn-classroom-desk").count(), 6);
  assert.equal(await classroom.locator(".cn-classroom-chair").count(), 6);
  assert(await page.locator(".cn-wall-face").count() > 0);

  await page.locator("#rotateMapBtn").click();
  await page.locator("#fitBtn").click();
  await page.screenshot({ path: path.join(outputDir, "latest-635-g31.png"), fullPage: true });

  assert.deepEqual(errors, [], "Browser errors: " + errors.join(" | "));
  console.log(
    "Latest request verified: stable G31 label, visible selected room labels, one-frame 180 degree rotation, " +
    "six-desk classrooms, clear wall faces, and 635 to G31 skips every intermediate floor."
  );
  await browser.close();
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
