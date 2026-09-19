const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("C:/Users/Senthil/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");

const baseUrl = process.env.NAVORA_URL || "http://127.0.0.1:3000/?api=/api";
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
    await page.waitForSelector("#floorOverviewButtons [data-floor='F3']");
    await page.locator("#floorOverviewButtons [data-floor='F3']").click();
    await page.waitForSelector("#svgHost svg[data-floor='F3']");
    await page.locator('button[data-map-mode="25d"]').click();
    await page.waitForSelector("#svgHost svg.cn-map-25d[data-floor='F3']");

    for (const material of ["classroom", "bathroom", "courtyard", "lift", "stair", "seating"]) {
      assert.equal(await page.locator(`#cn-glitter-${material}`).count(), 1, `${material} glitter material missing`);
    }
    for (const selector of [".cn-space-lift", ".cn-space-stair", ".cn-flat-space-open", ".cn-flat-space-seating"]) {
      const target = page.locator(`#svgHost svg ${selector}`).first();
      assert(await target.count(), `${selector} is missing on F3`);
      assert.match(await target.evaluate(element => getComputedStyle(element).fill), /cn-glitter-/);
    }
    assert(await page.locator("#svgHost svg .cn-classroom-detail").count(), "Classroom interior details are missing");
    assert(await page.locator("#svgHost svg .cn-bathroom-detail").count(), "Bathroom interior details are missing");
    const roomCode = page.locator("#campusnav-map-labels .cn-room-code").first();
    assert.equal(await roomCode.evaluate(element => getComputedStyle(element).fill), "rgb(255, 255, 255)");
    assert(Number(await roomCode.evaluate(element => getComputedStyle(element).fontWeight)) >= 900);

    await page.screenshot({
      path: path.join(outputDir, "navora-luminous-f3.jpg"),
      fullPage: true,
      type: "jpeg",
      quality: 72,
    });
    assert.deepEqual(errors, [], "Browser errors: " + errors.join(" | "));
    console.log("Luminous F3 materials passed for classrooms, bathrooms, open space, seating, lifts, stairs, and room labels.");
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
