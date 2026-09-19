"""DEV-ONLY: drive the running app in headless Chromium and capture screenshots."""
import sys
import time

from playwright.sync_api import sync_playwright

OUT = "/home/claude/prp/shots"
URL = "http://127.0.0.1:5500/"


def run(tag="base", mobile=False, plan=True):
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--force-color-profile=srgb"])
        pg = b.new_page(
            viewport={"width": 390, "height": 844} if mobile else {"width": 1440, "height": 900},
            device_scale_factor=2,
            is_mobile=mobile,
            has_touch=mobile,
        )
        errors = []
        pg.on("console", lambda m: errors.append(f"[{m.type}] {m.text}") if m.type in ("error", "warning") else None)
        pg.on("pageerror", lambda e: errors.append(f"[pageerror] {e}"))

        pg.goto(URL, wait_until="networkidle")
        pg.wait_for_timeout(2500)
        pg.screenshot(path=f"{OUT}/{tag}-01-initial.png")

        if plan:
            pg.fill("#startSearch", "G41")
            pg.wait_for_timeout(700)
            pg.screenshot(path=f"{OUT}/{tag}-02-search.png")
            pg.keyboard.press("Enter")
            pg.wait_for_timeout(500)

            pg.fill("#destinationSearch", "421")
            pg.wait_for_timeout(700)
            pg.keyboard.press("Enter")
            pg.wait_for_timeout(400)

            pg.click("#navigateBtn")
            pg.wait_for_timeout(3500)
            pg.screenshot(path=f"{OUT}/{tag}-03-route.png")

            # advance a few checkpoints
            for i in range(3):
                try:
                    pg.click("#confirmNextBtn", timeout=3000)
                    pg.wait_for_timeout(1400)
                except Exception as exc:
                    errors.append(f"[advance{i}] {exc}")
                    break
            pg.screenshot(path=f"{OUT}/{tag}-04-progress.png")

        print(f"--- {tag} console ---")
        for e in errors[:25]:
            print("  ", e[:220])
        b.close()


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "base",
        mobile=("mobile" in sys.argv),
        plan=("noplan" not in sys.argv))
