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
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));

  const response = await page.request.get(
    "http://127.0.0.1:3000/api/route?start_floor=F5&start=530&destination_floor=F5&destination=538&mode=stairs"
  );
  assert.equal(response.status(), 200, "530 to 538 must be routable");
  const route = await response.json();
  assert.equal(route.raw_node_path.at(0), "530");
  assert.equal(route.raw_node_path.at(-1), "538");
  assert.equal(
    route.checkpoints.length,
    route.raw_node_path.length,
    "every raw route node must be a confirmable checkpoint"
  );
  assert(route.checkpoints.some((point) => point.node_id === "F5_538_DOOR"));
  assert(route.checkpoints.filter((point) => point.is_turn).length >= 4);

  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.waitForSelector("#startSearch:not([disabled])");
  await page.locator("#startSearch").fill("530");
  await page.locator("#startSuggestions .suggestion-item", { hasText: "530" }).first().click();
  await page.locator("#destinationSearch").fill("538");
  await page.locator("#destinationSuggestions .suggestion-item", { hasText: "538" }).first().click();
  await page.locator("#navigateBtn").click();
  await page.waitForSelector("body.route-active #stepBar:not([hidden])");

  assert.match(await page.locator("#confirmNextBtn").innerText(), /Next point 2/);
  assert.match(await page.locator("#nextStepTitle").innerText(), /Point 2/);
  const checkpointNumbers = await page.locator(".cn-checkpoint-number").evaluateAll((items) =>
    items.filter((item) => getComputedStyle(item).display !== "none").map((item) => item.textContent)
  );
  assert(checkpointNumbers.includes("1"), "current point number must be visible");
  assert(checkpointNumbers.includes("2"), "next point number must be visible");
  assert(checkpointNumbers.includes(String(route.checkpoints.length)), "destination point number must be visible");
  assert(
    await page.locator(".cn-checkpoint-turn").count() >= 4,
    "every significant turn must be rendered as a numbered checkpoint"
  );

  await page.locator("#confirmNextBtn").click();
  await page.waitForFunction(() => /Next point 3/.test(document.querySelector("#confirmNextBtn")?.textContent || ""));
  await page.screenshot({ path: path.join(outputDir, "route-530-538.png"), fullPage: true });
  await page.locator("#clearRouteBtn").click();

  for (const floor of ["G", "F1", "F2", "F3", "F4", "F5", "F6", "F7"]) {
    await page.locator(`[data-floor="${floor}"]`).first().click();
    await page.waitForSelector(`#svgHost svg[data-floor="${floor}"]`);
    const wallScale = await page.locator("#svgHost svg").evaluate(svg => {
      const wallWidth = parseFloat(svg.style.getPropertyValue("--cn-wall-top-width"));
      const depth = Number(svg.dataset.wallDepth);
      const wallMetric = Number(svg.dataset.wallMinDimension);
      return { wallWidth, depthRatio: depth / wallMetric };
    });
    assert(Math.abs(wallScale.wallWidth - 3.9) < .001, `${floor} must use the shared wall-cap width`);
    assert(Math.abs(wallScale.depthRatio - .0377) < .00001, `${floor} must use the shared proportional wall depth`);
    assert.equal(await page.locator("#campusnav-floor-corridors").count(), 0, `${floor} must not render corridor paint`);
    assert(await page.locator(".cn-open-space-surface").count() > 0, `${floor} must show flat open-space surfaces`);
    assert(await page.locator(".cn-open-perimeter").count() > 0, `${floor} must show low open-space perimeter walls`);
    assert(await page.locator(".cn-seating-detail").count() > 0, `${floor} must show furnished seating detail`);
    assert(await page.locator(".cn-room-door").count() > 0, `${floor} must show non-classroom service access`);
    assert.equal(
      await page.locator('.cn-room-door[data-room-kind="classroom"]').count(),
      0,
      `${floor} must not show door symbols in front of classrooms`
    );
    assert(await page.locator(".cn-classroom-detail").count() > 0, `${floor} must show classroom furniture`);
    assert(await page.locator(".cn-bathroom-detail").count() > 0, `${floor} must show bathroom fixtures`);
    assert.equal(
      await page.locator(".cn-bathroom-symbol").count(),
      await page.locator(".cn-bathroom-detail").count(),
      `${floor} must place one restroom symbol inside every decorated bathroom`
    );
    assert.equal(await page.locator(".cn-label-bathroom", { hasText: "🚻" }).count(), 0, `${floor} bathroom labels must not use floating emoji`);
    assert.equal(await page.locator("#campusnav-wall-outline").count(), 1, `${floor} must have crisp wall outlines`);
    const filters = await page.locator(".cn-open-space-surface").evaluateAll((items) =>
      items.map((item) => getComputedStyle(item).filter)
    );
    assert(filters.every((filter) => filter === "none"), `${floor} open spaces must not use 2.5D shadows`);
    if (floor === "F3") {
      await page.screenshot({ path: path.join(outputDir, "floor-f3-map-detail.png"), fullPage: true });
    }
  }

  await page.locator('[data-floor="G"]').first().click();
  await page.waitForSelector('#svgHost svg[data-floor="G"]');
  assert(await page.locator(".cn-building-entrance").count() >= 2, "Ground Floor must show both building entries");
  assert.equal(await page.locator(".brand-name").innerText(), "Navora");

  const wallSafeResponse = await page.request.get(
    "http://127.0.0.1:3000/api/route?start_floor=F5&start=535&destination_floor=F5&destination=532&mode=stairs"
  );
  assert.equal(wallSafeResponse.status(), 200);
  const wallSafeRoute = await wallSafeResponse.json();
  const routePoints = new Map(wallSafeRoute.floor_routes.F5.map((point) => [point.node_id, point]));
  assert.equal(routePoints.get("F5_ellipse48").x, 316, "ellipse48 must sit on the corridor centerline");
  assert.equal(routePoints.get("F5_ellipse49").x, 316, "ellipse49 must sit on the corridor centerline");

  const stair3Response = await page.request.get(
    "http://127.0.0.1:3000/api/route?start_floor=F1&start=STAIRS3-F1-D&destination_floor=F3&destination=STAIRS3-F3-U&mode=stairs"
  );
  assert.equal(stair3Response.status(), 200);
  const stair3Route = await stair3Response.json();
  assert.deepEqual(
    stair3Route.floors,
    ["F1", "F3"],
    "Stair 3 must travel directly without drawing an intermediate-floor path"
  );
  assert.deepEqual(Object.keys(stair3Route.floor_routes), ["F1", "F3"]);

  await page.locator("#startSearch").fill("535");
  await page.locator("#startSuggestions .suggestion-item", { hasText: "535" }).first().click();
  await page.locator("#destinationSearch").fill("532");
  await page.locator("#destinationSuggestions .suggestion-item", { hasText: "532" }).first().click();
  await page.locator("#navigateBtn").click();
  await page.waitForSelector("body.route-active #stepBar:not([hidden])");
  await page.screenshot({ path: path.join(outputDir, "wall-safe-535-532.png"), fullPage: true });

  assert.deepEqual(errors, [], `Browser errors: ${errors.join(" | ")}`);
  console.log(
    `Navora verified: 530→538 has ${route.checkpoints.length} point-by-point checkpoints and ` +
    `${route.checkpoints.filter((point) => point.is_turn).length} turns; corridor paint removed; ` +
    `entries, classroom doors removed, service access, direct Stair 3 floor travel, in-room bathroom symbols, open-space walls, and the 535→532 wall-safe route verified; browser errors=0.`
  );
  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
