"""Summarize blueprint labels around the navigation database's room codes."""

from __future__ import annotations

import json
import math
import re
import sqlite3
import sys
from pathlib import Path

import pdfplumber


ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = ROOT / "tmp" / "pdfs" / "blueprint-db-audit-20260917" / "blueprint"
DATABASE = ROOT / "integration" / "building_navigation.db"
KEYWORD_PATTERN = re.compile(
    r"TOILET|CLASS|SMART|LAB|FACULTY|OFFICE|ELECTRICAL|COMMUNICATION|BREAK|CUT.?OUT|OPEN|SEATING|COURTYARD|REFUGE|TERRACE|PANTRY|JANITOR|RESEARCH|DEAN|HOD",
    re.IGNORECASE,
)


def floor_from_name(name: str) -> str:
    if "Ground" in name:
        return "G"
    match = re.search(r"(\d+)(?:st|nd|rd|th)", name)
    return f"F{match.group(1)}" if match else name


def center(word: dict[str, object]) -> tuple[float, float]:
    return (
        (float(word["x0"]) + float(word["x1"])) / 2,
        (float(word["top"]) + float(word["bottom"])) / 2,
    )


def main() -> None:
    requested_floor = sys.argv[1].upper() if len(sys.argv) > 1 else None
    connection = sqlite3.connect(DATABASE)
    codes_by_floor = {
        floor: [row[0] for row in connection.execute("SELECT code FROM locations WHERE floor_id = ? ORDER BY code", (floor,))]
        for floor in ["G", "F1", "F2", "F3", "F4", "F5", "F6", "F7"]
    }
    connection.close()

    for pdf_path in sorted(PDF_DIR.glob("*.pdf"), key=lambda path: floor_from_name(path.name)):
        floor = floor_from_name(pdf_path.name)
        if requested_floor and floor != requested_floor:
            continue
        with pdfplumber.open(pdf_path) as pdf:
            page = pdf.pages[0]
            words = page.extract_words(
                x_tolerance=1,
                y_tolerance=1,
                keep_blank_chars=False,
                use_text_flow=False,
                extra_attrs=["size"],
            )
            keywords = [word for word in words if KEYWORD_PATTERN.search(str(word["text"]))]
            print(f"\n## {floor} — {pdf_path.name}")
            print("Keywords:")
            for word in keywords:
                x, y = center(word)
                print(f"  {word['text']!s:<22} x={x:6.1f} y={y:6.1f} size={float(word['size']):4.1f}")
            print("Room-code candidates:")
            for code in codes_by_floor[floor]:
                exact = [word for word in words if str(word["text"]).strip().upper() == code.upper()]
                if not exact:
                    print(f"  {code:<6} MISSING")
                    continue
                candidates = []
                for word in exact:
                    x, y = center(word)
                    if float(word["size"]) < 6:
                        continue
                    ranked_keywords = []
                    for keyword in keywords:
                        kx, ky = center(keyword)
                        ranked_keywords.append((math.hypot(kx - x, ky - y), str(keyword["text"])))
                    nearest = ", ".join(
                        f"{label}@{distance:.0f}" for distance, label in sorted(ranked_keywords)[:4]
                    )
                    nearby_words = []
                    for other in words:
                        ox, oy = center(other)
                        distance = math.hypot(ox - x, oy - y)
                        if other is not word and distance <= 48 and float(other["size"]) >= 3:
                            nearby_words.append((distance, str(other["text"])))
                    context = " ".join(label for _, label in sorted(nearby_words)[:16])
                    candidates.append(
                        f"x={x:.1f},y={y:.1f},size={float(word['size']):.1f}; near {nearest}; context [{context}]"
                    )
                if not candidates:
                    print(f"  {code:<6} no title-sized occurrence")
                    continue
                print(f"  {code:<6} " + " | ".join(candidates))


if __name__ == "__main__":
    main()
