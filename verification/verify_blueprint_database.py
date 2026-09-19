"""Verify every integrated location matches the explicit blueprint mapping."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.apply_blueprint_room_types import BLUEPRINT_ROOMS, DATABASE  # noqa: E402


def main() -> None:
    expected = {
        (floor_id, code): metadata
        for floor_id, floor_records in BLUEPRINT_ROOMS.items()
        for code, metadata in floor_records.items()
    }
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    try:
        rows = {
            (row["floor_id"], row["code"]): row
            for row in connection.execute("SELECT * FROM locations")
        }
        assert set(rows) == set(expected), "Database codes differ from the blueprint mapping"
        for key, (expected_name, expected_type) in expected.items():
            row = rows[key]
            assert row["name"] == expected_name, (key, row["name"], expected_name)
            assert row["type"] == expected_type, (key, row["type"], expected_type)
            assert str(row["description"]).startswith("Blueprint-verified"), key
            if not row["searchable"]:
                assert "No routable navigation node" in row["description"], key
        print(f"Blueprint database verified: {len(rows)} of {len(expected)} records match.")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
