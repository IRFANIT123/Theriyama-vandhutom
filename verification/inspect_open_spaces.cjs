const { chromium } = require("C:/Users/Senthil/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto("http://127.0.0.1:3000/?api=/api", { waitUntil: "networkidle" });
  await page.waitForSelector("#svgHost svg");
  for (const floorId of ["G", "F1", "F2", "F3", "F4", "F5", "F6", "F7"]) {
    await page.locator(`[data-floor="${floorId}"]`).first().click();
    await page.waitForSelector(`#svgHost svg[data-floor="${floorId}"]`);
    const surfaces = await page.locator("#campusnav-open-spaces .cn-open-space-surface").evaluateAll((items) =>
      items.map((item, index) => ({
        index,
        x: Number(item.getAttribute("x")),
        y: Number(item.getAttribute("y")),
        width: Number(item.getAttribute("width")),
        height: Number(item.getAttribute("height")),
        aria: item.getAttribute("aria-label"),
      }))
    );
    console.log(`${floorId} ${JSON.stringify(surfaces)}`);
  }
  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
