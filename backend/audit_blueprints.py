"""Extract room-code and space-label evidence from the supplied blueprint PDFs."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pdfplumber


ROOT = Path(__file__).resolve().parents[1]
BLUEPRINT_DIR = ROOT / "tmp" / "pdfs" / "blueprint-db-audit-20260917" / "blueprint"
DATABASE_AUDIT = ROOT / "integration" / "building_navigation.db"
KEYWORDS = re.compile(
    r"TOILET|CLASS|SMART|LAB|FACULTY|OFFICE|ELECTRICAL|COMMUNICATION|BREAK|CUT.?OUT|OPEN|SEATING|COURTYARD|REFUGE|TERRACE|PANTRY|JANITOR",
    re.IGNORECASE,
)


def center(word: dict[str, object]) -> tuple[float, float]:
    return (
        (float(word["x0"]) + float(word["x1"])) / 2,
        (float(word["top"]) + float(word["bottom"])) / 2,
    )


def nearby(words: list[dict[str, object]], anchor: dict[str, object], limit: int = 18) -> list[dict[str, object]]:
    ax, ay = center(anchor)
    ranked = []
    for word in words:
        wx, wy = center(word)
        distance = math.hypot(wx - ax, wy - ay)
        if word is anchor or distance > 120:
            continue
        ranked.append((distance, word))
    return [
        {
            "text": str(word["text"]),
            "x": round(center(word)[0], 1),
            "y": round(center(word)[1], 1),
            "distance": round(distance, 1),
        }
        for distance, word in sorted(ranked, key=lambda item: item[0])[:limit]
    ]


def floor_from_name(name: str) -> str:
    if "Ground" in name:
        return "G"
    match = re.search(r"(\d+)(?:st|nd|rd|th)", name)
    return f"F{match.group(1)}" if match else name


def main() -> None:
    for pdf_path in sorted(BLUEPRINT_DIR.glob("*.pdf"), key=lambda path: floor_from_name(path.name)):
        floor = floor_from_name(pdf_path.name)
        with pdfplumber.open(pdf_path) as pdf:
            page = pdf.pages[0]
            words = page.extract_words(
                x_tolerance=2,
                y_tolerance=2,
                keep_blank_chars=False,
                use_text_flow=False,
            )
            print(json.dumps({"floor": floor, "pdf": pdf_path.name, "width": page.width, "height": page.height}))
            for word in words:
                text = str(word["text"]).strip()
                is_code = bool(
                    re.fullmatch(r"G(?:2[8-9]|3\d|4[0-2])", text, re.IGNORECASE)
                    or re.fullmatch(r"[1-7]\d{2}(?:-A)?", text, re.IGNORECASE)
                )
                if is_code:
                    print(
                        json.dumps(
                            {
                                "kind": "room_code",
                                "floor": floor,
                                "text": text,
                                "x": round(center(word)[0], 1),
                                "y": round(center(word)[1], 1),
                                "nearby": nearby(words, word),
                            },
                            ensure_ascii=False,
                        )
                    )
            for word in words:
                text = str(word["text"]).strip()
                if KEYWORDS.search(text):
                    print(
                        json.dumps(
                            {
                                "kind": "keyword",
                                "floor": floor,
                                "text": text,
                                "x": round(center(word)[0], 1),
                                "y": round(center(word)[1], 1),
                            },
                            ensure_ascii=False,
                        )
                    )


if __name__ == "__main__":
    main()
