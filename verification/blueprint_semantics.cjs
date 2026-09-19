const assert = require("node:assert/strict");
const { chromium } = require("C:/Users/Senthil/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");

const bathrooms = {
  G: ["G28", "G29", "G30", "G35", "G36"],
  F1: ["131", "132", "133", "139", "140"],
  F2: ["227", "228", "235", "236"],
  F3: ["326", "327", "328", "335", "336"],
  F4: ["421", "422", "423", "430", "431"],
  F5: ["526", "527", "528", "535", "536"],
  F6: ["626", "627", "628", "635", "636"],
  F7: ["728", "729", "730", "737", "738"],
};

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

  for (const [floorId, expectedCodes] of Object.entries(bathrooms)) {
    await page.locator(`[data-floor="${floorId}"]`).first().click();
    await page.waitForSelector(`#svgHost svg[data-floor="${floorId}"]`);
    const actualCodes = await page.locator(".cn-label-bathroom").evaluateAll((labels) =>
      labels.map((label) => label.textContent.replace("🚻", "").replace("Bathroom", "").trim().replace(/^G-/, "G"))
    );
    for (const code of expectedCodes) {
      assert(actualCodes.some((value) => value.startsWith(code)), `${floorId} must show ${code} as a bathroom`);
    }
    const kinds = await page.locator(".cn-open-space-surface").evaluateAll((items) =>
      [...new Set(items.map((item) => item.dataset.flatSpaceKind))]
    );
    assert(kinds.includes("open"), `${floorId} must include a flat open-to-sky zone`);
    assert(kinds.includes("seating"), `${floorId} must include a flat cut-out seating zone`);
    assert.equal(await page.locator(".cn-space-depth .cn-open-space-surface").count(), 0);
    if (floorId === "F3") {
      const anchorDistance = await page.locator('[data-map-label][aria-label^="326 ·"]').evaluate((label) => {
        const svg = label.ownerSVGElement;
        const node = svg.querySelector('[id="326"]');
        const labelBox = label.getBoundingClientRect();
        const point = new DOMPoint(Number(node.getAttribute("cx")), Number(node.getAttribute("cy")))
          .matrixTransform(node.getScreenCTM());
        return Math.hypot(labelBox.left + labelBox.width / 2 - point.x, labelBox.top + labelBox.height / 2 - point.y);
      });
      assert(anchorDistance < 80, `F3 room 326 label must stay anchored to its blueprint room; distance=${anchorDistance}`);
      console.log(`F3 room 326 label-to-node distance: ${anchorDistance.toFixed(1)}px`);
      await page.screenshot({ path: "verification/output/floor-f3-room-326.png", fullPage: true });
    }
  }

  assert.deepEqual(errors, [], `Browser errors: ${errors.join(" | ")}`);
  console.log("Blueprint UI verified across G-F7; bathrooms, classrooms, open spaces, and seating surfaces are correct; browser errors=0.");
  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
