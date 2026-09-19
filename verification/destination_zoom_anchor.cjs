const assert = require("node:assert/strict");
const { chromium } = require("C:/Users/Senthil/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");

const baseUrl = process.env.NAVORA_URL || "http://127.0.0.1:3000/?api=/api";

async function markerGeometry(page) {
  return page.evaluate(() => {
    const svg = document.querySelector("#svgHost svg");
    const marker = svg?.querySelector(".cn-checkpoint-destination");
    const route = svg?.querySelector(".cn-route-line");
    if (!svg || !marker) return null;

    const markerRect = marker.getBoundingClientRect();
    const markerCenter = {
      x: markerRect.left + markerRect.width / 2,
      y: markerRect.top + markerRect.height / 2,
    };
    const cx = Number(marker.getAttribute("cx"));
    const cy = Number(marker.getAttribute("cy"));
    const anchor = new DOMPoint(cx, cy).matrixTransform(svg.getScreenCTM());
    let endpoint = null;
    if (route?.points.numberOfItems) {
      const last = route.points.getItem(route.points.numberOfItems - 1);
      const screenPoint = new DOMPoint(last.x, last.y).matrixTransform(route.getScreenCTM());
      endpoint = { x: screenPoint.x, y: screenPoint.y };
    }
    return {
      markerCenter,
      anchor: { x: anchor.x, y: anchor.y },
      endpoint,
      offset: Math.hypot(markerCenter.x - anchor.x, markerCenter.y - anchor.y),
      radius: markerRect.width / 2,
      cx,
      cy,
      viewBox: svg.getAttribute("viewBox"),
      transform: getComputedStyle(marker).transform,
    };
  });
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.waitForSelector("#startSearch:not([disabled])");

    await page.locator("#startSearch").fill("530");
    await page.locator("#startSuggestions .suggestion-item").first().click();
    await page.locator("#destinationSearch").fill("538");
    await page.locator("#destinationSuggestions .suggestion-item").first().click();
    await page.locator("#navigateBtn").click();
    await page.waitForSelector("#svgHost svg .cn-checkpoint-destination");

    const confirm = page.locator("#confirmNextBtn");
    for (let safety = 0; safety < 50 && !(await confirm.isDisabled()); safety += 1) {
      await confirm.click();
      await page.waitForTimeout(80);
    }
    await page.waitForSelector("body.route-arrived #svgHost svg .cn-checkpoint-arrived");
    await page.waitForTimeout(650);

    const before = await markerGeometry(page);
    await page.locator("#zoomInBtn").click();
    await page.waitForTimeout(120);
    const zoomedInDuringAnimation = await markerGeometry(page);
    await page.waitForTimeout(500);
    const zoomedInSettled = await markerGeometry(page);
    await page.locator("#zoomOutBtn").click();
    await page.waitForTimeout(120);
    const zoomedOutDuringAnimation = await markerGeometry(page);

    assert(before && zoomedInDuringAnimation && zoomedInSettled && zoomedOutDuringAnimation,
      "Destination marker geometry was unavailable");
    console.log(JSON.stringify({ before, zoomedInDuringAnimation, zoomedInSettled, zoomedOutDuringAnimation }, null, 2));
    assert(before.offset < 0.75, `Initial marker offset was ${before.offset}px`);
    assert(zoomedInDuringAnimation.offset < 0.75,
      `Zoomed-in marker offset during animation was ${zoomedInDuringAnimation.offset}px`);
    assert(zoomedInSettled.offset < 0.75,
      `Settled zoomed-in marker offset was ${zoomedInSettled.offset}px`);
    assert(zoomedOutDuringAnimation.offset < 0.75,
      `Zoomed-out marker offset during animation was ${zoomedOutDuringAnimation.offset}px`);
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
