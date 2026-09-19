"""Print the navigation database schema and all stored location rows."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


DATABASE = Path(__file__).resolve().parents[1] / "integration" / "building_navigation.db"


def main() -> None:
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    try:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
        ]
        print("TABLES", json.dumps(tables))
        print(
            "LOCATIONS_SCHEMA",
            json.dumps([tuple(row) for row in connection.execute("PRAGMA table_info(locations)")]),
        )
        for row in connection.execute("SELECT * FROM locations ORDER BY floor_id, code"):
            print(json.dumps(dict(row), ensure_ascii=False, sort_keys=True))
    finally:
        connection.close()


if __name__ == "__main__":
    main()
