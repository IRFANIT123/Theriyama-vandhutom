#!/usr/bin/env python3
"""
fix_f6_f7_floor_name.py

Safely fixes only the missing `name` column in the `floors` table
for f6/prp_navigation.db and f7/prp_navigation.db.

What it does:
1. Creates a .backup copy of each database.
2. Opens the database.
3. Checks PRAGMA table_info(floors).
4. If `name` is missing, adds it.
5. Sets:
      F6 -> Sixth Floor
      F7 -> Seventh Floor
6. Prints the final floor record.

It does NOT modify nodes, edges, locations, or routing data.
"""

from pathlib import Path
import shutil
import sqlite3
import sys

PROJECT_ROOT = Path(__file__).resolve().parent

TARGETS = {
    "f6": ("F6", "Sixth Floor"),
    "f7": ("F7", "Seventh Floor"),
}

def column_names(cur, table):
    return [row[1] for row in cur.execute(f"PRAGMA table_info({table})")]

def fix_floor(folder_name, expected_floor_id, floor_name):
    folder = PROJECT_ROOT / folder_name
    db = folder / "prp_navigation.db"

    print("=" * 70)
    print(f"Checking {folder_name}: {db}")

    if not db.exists():
        print(f"ERROR: Database not found: {db}")
        return False

    backup = folder / "prp_navigation_before_name_fix.db"

    if not backup.exists():
        shutil.copy2(db, backup)
        print(f"Backup created: {backup.name}")
    else:
        print(f"Backup already exists: {backup.name}")

    con = sqlite3.connect(db)

    try:
        cur = con.cursor()

        tables = {
            row[0]
            for row in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

        if "floors" not in tables:
            print("ERROR: `floors` table is missing.")
            return False

        cols = column_names(cur, "floors")
        print("Current floors columns:", ", ".join(cols))

        if "name" not in cols:
            cur.execute("ALTER TABLE floors ADD COLUMN name TEXT")
            print("Added missing column: name")
        else:
            print("Column `name` already exists; no ALTER needed.")

        floor_rows = cur.execute("SELECT floor_id FROM floors").fetchall()

        if len(floor_rows) != 1:
            print(
                f"ERROR: Expected exactly 1 row in floors table, "
                f"found {len(floor_rows)}."
            )
            return False

        actual_floor_id = str(floor_rows[0][0])

        if actual_floor_id != expected_floor_id:
            print(
                f"WARNING: Expected floor_id {expected_floor_id}, "
                f"but database contains {actual_floor_id}."
            )

        cur.execute(
            "UPDATE floors SET name = ? WHERE floor_id = ?",
            (floor_name, actual_floor_id),
        )

        con.commit()

        cols_after = column_names(cur, "floors")

        select_cols = ["floor_id"]
        if "floor_number" in cols_after:
            select_cols.append("floor_number")
        select_cols.append("name")
        if "display_order" in cols_after:
            select_cols.append("display_order")

        row = cur.execute(
            f"SELECT {', '.join(select_cols)} FROM floors"
        ).fetchone()

        print("Final columns:", ", ".join(cols_after))
        print("Final floor record:")
        print(dict(zip(select_cols, row)))
        print("RESULT: PASS")
        return True

    except Exception as exc:
        con.rollback()
        print(f"ERROR: {exc}")
        return False

    finally:
        con.close()

def main():
    all_ok = True

    for folder_name, (floor_id, floor_name) in TARGETS.items():
        ok = fix_floor(folder_name, floor_id, floor_name)
        all_ok = all_ok and ok
        print()

    print("=" * 70)
    if all_ok:
        print("F6/F7 SCHEMA FIX COMPLETE")
        print("Now rerun validate_all_floors.py.")
        return 0

    print("F6/F7 SCHEMA FIX FAILED — check the messages above.")
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
