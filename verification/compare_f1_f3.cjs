const assert = require("node:assert/strict");
const { chromium } = require("C:/Users/Senthil/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto("http://127.0.0.1:3000/?api=/api", { waitUntil: "networkidle" });
  const output = {};

  for (const floor of ["F1", "F3"]) {
    await page.locator('[data-floor="' + floor + '"]').first().click();
    await page.waitForSelector('#svgHost svg[data-floor="' + floor + '"]');
    output[floor] = await page.locator("#svgHost svg").evaluate(svg => {
      const screenScale = element => {
        const matrix = element.getScreenCTM();
        return matrix ? Math.hypot(matrix.a, matrix.b) : 0;
      };
      const screenBox = element => {
        const rect = element.getBoundingClientRect();
        return { width: rect.width, height: rect.height };
      };
      const median = values => {
        const sorted = values.filter(Number.isFinite).sort((a, b) => a - b);
        return sorted.length ? sorted[Math.floor(sorted.length / 2)] : 0;
      };
      const outline = svg.querySelector(".cn-wall-outline-shape");
      const wallTop = svg.querySelector(".cn-architecture path,.cn-architecture line,.cn-architecture polyline");
      const wallLayer = svg.querySelector(".cn-architecture");
      const wallFace = svg.querySelector(".cn-wall-face");
      const firstDetail = svg.querySelector(".cn-classroom-detail");
      const roomLayer = firstDetail?.parentElement;
      const relativeScale = element => {
        const root = svg.getCTM();
        const local = element?.getCTM();
        if (!root || !local) return 0;
        const matrix = root.inverse().multiply(local);
        return Math.hypot(matrix.a, matrix.b);
      };
      const rootBounds = element => {
        const box = element.getBBox();
        const root = svg.getCTM();
        const local = element.getCTM();
        if (!root || !local) return { width: 0, height: 0 };
        const matrix = root.inverse().multiply(local);
        const corners = [
          [box.x, box.y],
          [box.x + box.width, box.y],
          [box.x, box.y + box.height],
          [box.x + box.width, box.y + box.height],
        ].map(([x, y]) => new DOMPoint(x, y).matrixTransform(matrix));
        const xs = corners.map(point => point.x);
        const ys = corners.map(point => point.y);
        return {
          width: Math.max(...xs) - Math.min(...xs),
          height: Math.max(...ys) - Math.min(...ys),
        };
      };
      const details = [...svg.querySelectorAll(".cn-classroom-detail")];
      const detailBoxes = details.map(screenBox);
      const deskBoxes = [...svg.querySelectorAll(".cn-classroom-desk")].map(screenBox);
      return {
        sourceMin: Number(svg.dataset.sourceMinDimension),
        wallMin: Number(svg.dataset.wallMinDimension),
        wallDepthScreen: Number(svg.dataset.wallDepth) * screenScale(wallFace),
        displayed: screenBox(svg),
        outlineStrokeCss: parseFloat(getComputedStyle(outline).strokeWidth),
        outlineVectorEffect: getComputedStyle(outline).vectorEffect,
        outlineScale: screenScale(outline),
        wallLayerToRootScale: relativeScale(wallLayer),
        wallLayerRootBounds: rootBounds(wallLayer),
        wallLayerScreenBounds: screenBox(wallLayer),
        wallTopStrokeCss: parseFloat(getComputedStyle(wallTop).strokeWidth),
        wallTopScale: screenScale(wallTop),
        roomLayerToRootScale: relativeScale(roomLayer),
        detailScreenScale: screenScale(firstDetail),
        classroomDetails: details.length,
        medianDetailWidth: median(detailBoxes.map(box => box.width)),
        medianDetailHeight: median(detailBoxes.map(box => box.height)),
        medianDeskWidth: median(deskBoxes.map(box => box.width)),
        medianDeskHeight: median(deskBoxes.map(box => box.height)),
      };
    });
  }

  assert(Math.abs(output.F1.outlineStrokeCss - output.F3.outlineStrokeCss) < .1);
  const f1TopScreen = output.F1.wallTopStrokeCss * output.F1.wallTopScale;
  const f3TopScreen = output.F3.wallTopStrokeCss * output.F3.wallTopScale;
  assert(Math.abs(f1TopScreen - f3TopScreen) < .15);
  assert(Math.abs(output.F1.wallDepthScreen - output.F3.wallDepthScreen) < .25);
  assert(Math.abs(output.F1.medianDetailWidth - output.F3.medianDetailWidth) < 3);
  assert(Math.abs(output.F1.medianDeskWidth - output.F3.medianDeskWidth) < 1);
  console.log(JSON.stringify(output, null, 2));
  await browser.close();
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
