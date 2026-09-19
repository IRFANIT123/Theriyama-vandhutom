const assert = require("node:assert/strict");
const { chromium } = require("C:/Users/Senthil/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("http://127.0.0.1:3000/?api=/api", { waitUntil: "networkidle" });

  const allRooms = [];
  for (const floorId of ["G", "F1", "F2", "F3", "F4", "F5", "F6", "F7"]) {
    const response = await page.request.get(`http://127.0.0.1:3000/api/locations?floor_id=${floorId}&include_non_searchable=false`);
    assert.equal(response.status(), 200);
    allRooms.push(...await response.json());
  }
  const thirdFloorRooms = allRooms.filter(item => item.floor_id === "F3");

  await page.locator("#globalSearch").fill("3rd");
  await page.waitForSelector("#globalSuggestions .suggestion-item");
  assert.equal(await page.locator("#globalSuggestions .suggestion-item").count(), thirdFloorRooms.length);
  assert((await page.locator("#globalSuggestions .suggestion-copy span").allTextContents()).every(text => text.startsWith("Floor 3")));

  await page.locator("#globalSearch").fill("3");
  assert.equal(await page.locator("#globalSuggestions .suggestion-item").count(), allRooms.length);
  const preferred = await page.locator("#globalSuggestions .suggestion-item").evaluateAll((items, count) =>
    items.slice(0, count).every(item => item.querySelector(".suggestion-copy span").textContent.startsWith("Floor 3")), thirdFloorRooms.length
  );
  assert(preferred, "single digit 3 must prioritize every third-floor room");

  await page.locator("#globalSearch").fill("every room");
  assert.equal(await page.locator("#globalSuggestions .suggestion-item").count(), allRooms.length);

  await page.locator("#destinationSearch").fill("third floor");
  await page.waitForSelector("#destinationSuggestions .suggestion-item");
  assert.equal(await page.locator("#destinationSuggestions .suggestion-item").count(), thirdFloorRooms.length);

  await page.locator("#destinationSearch").fill("every room");
  assert.equal(await page.locator("#destinationSuggestions .suggestion-item").count(), allRooms.length);

  await page.locator("#destinationSearch").fill("530");
  assert((await page.locator("#destinationSuggestions .suggestion-item").first().innerText()).startsWith("□\n530"));

  assert.deepEqual(errors, [], `Browser errors: ${errors.join(" | ")}`);
  console.log(`Search discovery verified: ${thirdFloorRooms.length} Floor 3 rooms prioritized; ${allRooms.length} available rooms exposed; browser errors=0.`);
  await browser.close();
})().catch(error => { console.error(error); process.exitCode = 1; });
