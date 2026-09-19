"""DEV-ONLY end-to-end verification of the navigation flow."""
import sys

from playwright.sync_api import sync_playwright

OUT = "/home/claude/prp/shots"
URL = "http://127.0.0.1:5500/"
fails, notes = [], []


def check(name, ok, detail=""):
    (notes if ok else fails).append(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))


def run(mobile=False):
    tag = "m" if mobile else "d"
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(
            viewport={"width": 390, "height": 844} if mobile else {"width": 1440, "height": 900},
            device_scale_factor=2, is_mobile=mobile, has_touch=mobile,
        )
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)

        pg.goto(URL, wait_until="networkidle")
        pg.wait_for_timeout(2200)

        check(f"[{tag}] boot: API online", "online" in (pg.get_attribute("#apiPill", "class") or ""))
        check(f"[{tag}] boot: floor rail populated",
              pg.locator("#floorOverviewButtons button").count() == 8,
              f"{pg.locator('#floorOverviewButtons button').count()} buttons")
        check(f"[{tag}] boot: floor SVG rendered", pg.locator("#svgHost svg").count() == 1)
        check(f"[{tag}] boot: no duplicate floor selector",
              pg.locator("#floorButtons").count() == 0)

        # --- search ---------------------------------------------------------
        pg.fill("#startSearch", "G41")
        pg.wait_for_timeout(600)
        check(f"[{tag}] search: start suggestions appear",
              pg.locator("#startSuggestions .suggestion-item").count() > 0)
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(300)
        check(f"[{tag}] search: start confirmed",
              not pg.locator("#startSelection").is_hidden())

        pg.fill("#destinationSearch", "421")
        pg.wait_for_timeout(600)
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(300)

        # --- route ----------------------------------------------------------
        pg.click("#navigateBtn")
        pg.wait_for_timeout(3000)
        check(f"[{tag}] route: dock visible", pg.locator("#stepBar").is_visible())
        check(f"[{tag}] route: body.route-active",
              "route-active" in (pg.get_attribute("body", "class") or ""))
        check(f"[{tag}] route: planning view hidden while navigating",
              not pg.locator(".planning-view").is_visible())
        check(f"[{tag}] route: polyline drawn on start floor",
              pg.locator("#svgHost svg .cn-route-line").count() >= 1)
        check(f"[{tag}] route: next-node pulse present",
              pg.locator("#svgHost svg .cn-next-pulse").count() >= 1)
        check(f"[{tag}] route: destination distinct from current mid-route",
              pg.locator("#svgHost svg .cn-checkpoint-arrived").count() == 0)
        counter = pg.inner_text("#dockPointCounter")
        check(f"[{tag}] route: point counter populated", "of" in counter, counter)

        total = int(counter.split("of")[1].split("·")[0].strip())

        # --- walk the whole route -------------------------------------------
        pass_through_ok = False
        tapped_map_node = False
        for step in range(total + 2):
            if pg.locator("#confirmNextBtn").is_disabled():
                break
            # Alternate: tap the node on the map itself (the primary UX) and
            # use the dock button, so both paths get exercised.
            node = pg.locator("#svgHost svg circle.cn-checkpoint-next")
            if step % 3 == 1 and node.count() > 0:
                try:
                    node.first.click(timeout=2500, force=True)
                    tapped_map_node = True
                except Exception:
                    pg.click("#confirmNextBtn")
            else:
                pg.click("#confirmNextBtn")
            pg.wait_for_timeout(900)

            lines = pg.locator("#svgHost svg .cn-route-line").count()
            rings = pg.locator("#svgHost svg .cn-connector-callout-ring").count()
            if lines == 0 and rings > 0:
                pass_through_ok = True
                pg.screenshot(path=f"{OUT}/verify-{tag}-passthrough.png")

        check(f"[{tag}] progress: map node tap advances route", tapped_map_node)
        check(f"[{tag}] progress: pass-through floor shows a callout", pass_through_ok,
              "no single-point floor encountered" if not pass_through_ok else "")

        # --- arrival --------------------------------------------------------
        pct = pg.inner_text("#dockProgressPercent")
        check(f"[{tag}] arrival: progress reaches 100%", pct.startswith("100"), pct)
        check(f"[{tag}] arrival: body.route-arrived set",
              "route-arrived" in (pg.get_attribute("body", "class") or ""))
        check(f"[{tag}] arrival: confirm button disabled", pg.locator("#confirmNextBtn").is_disabled())
        check(f"[{tag}] arrival: destination marker in arrived state",
              pg.locator("#svgHost svg .cn-checkpoint-arrived").count() >= 1)
        pg.screenshot(path=f"{OUT}/verify-{tag}-arrived.png")

        # --- undo -----------------------------------------------------------
        pg.click("#previousCheckpointBtn")
        pg.wait_for_timeout(1000)
        check(f"[{tag}] undo: arrival state cleared",
              "route-arrived" not in (pg.get_attribute("body", "class") or ""))

        # --- clear ----------------------------------------------------------
        if not mobile:
            pg.click("#clearRouteBtn")
            pg.wait_for_timeout(700)
            check(f"[{tag}] clear: planner returns",
                  pg.locator(".planning-view").is_visible())
            check(f"[{tag}] clear: dock hidden", not pg.locator("#stepBar").is_visible())

        check(f"[{tag}] no runtime JS errors", not errs, "; ".join(errs[:3]))
        b.close()


def a11y():
    """Keyboard reachability and contrast-critical labelling."""
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        pg.goto(URL, wait_until="networkidle")
        pg.wait_for_timeout(2000)

        reached = set()
        for _ in range(28):
            pg.keyboard.press("Tab")
            el = pg.evaluate("() => { const a=document.activeElement; return a ? (a.id||a.className||a.tagName) : '' }")
            reached.add(str(el))
        check("a11y: start input keyboard reachable", any("startSearch" in r for r in reached))
        check("a11y: navigate button keyboard reachable", any("navigateBtn" in r for r in reached))
        check("a11y: floor rail keyboard reachable", any("floor-overview-button" in r for r in reached))

        missing = pg.evaluate("""() => [...document.querySelectorAll('button')]
            .filter(b => !b.textContent.trim() && !b.getAttribute('aria-label')).length""")
        check("a11y: no unlabelled buttons", missing == 0, f"{missing} unlabelled")

        prog = pg.evaluate("""() => {const p=document.getElementById('journeyProgress');
            return p && p.getAttribute('role')==='progressbar' && p.hasAttribute('aria-valuenow')}""")
        check("a11y: progress bar has ARIA state", bool(prog))
        b.close()


def reduced_motion():
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
        pg.goto(URL, wait_until="networkidle")
        pg.wait_for_timeout(2000)
        pg.fill("#startSearch", "G41"); pg.wait_for_timeout(500); pg.keyboard.press("Enter")
        pg.fill("#destinationSearch", "421"); pg.wait_for_timeout(500); pg.keyboard.press("Enter")
        pg.click("#navigateBtn"); pg.wait_for_timeout(2500)
        anim = pg.evaluate("""() => {const n=document.querySelector('#svgHost svg .cn-next-pulse');
            if(!n) return 'missing';
            const s=getComputedStyle(n);
            return s.animationName + '|' + s.opacity }""")
        check("reduced-motion: next node still visible without animation",
              anim != "missing" and anim.startswith("none"), anim)
        b.close()


def error_state():
    """Point the frontend at a dead API and confirm it fails gracefully."""
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        pg.goto(URL + "?api=http://127.0.0.1:59999", wait_until="domcontentloaded")
        pg.wait_for_timeout(3500)
        cls = pg.get_attribute("#apiPill", "class") or ""
        check("error: offline status shown", "offline" in cls, cls)
        body = pg.inner_text("body")
        check("error: user-facing message, not a blank screen", len(body.strip()) > 40)
        check("error: map area is not stuck on a spinner",
              "Loading floor map" not in pg.inner_text("#mapLoading"),
              pg.inner_text("#mapLoading")[:60])
        pg.screenshot(path=f"{OUT}/verify-error.png")
        b.close()


if __name__ == "__main__":
    run(mobile=False)
    run(mobile=True)
    a11y()
    reduced_motion()
    error_state()
    print("\n".join(notes))
    print()
    if fails:
        print("\n".join(fails))
        print(f"\n{len(fails)} FAILED / {len(notes) + len(fails)} checks")
        sys.exit(1)
    print(f"ALL {len(notes)} CHECKS PASSED")
