#!/usr/bin/env python3
"""
integrate_building.py

PRP E-Block CampusNav building integration.

Reads:
  f0/prp_navigation.db
  f1/prp_navigation.db
  ...
  f7/prp_navigation.db

Creates:
  integration/building_navigation.db
  integration/integration_report.txt
  integration/cross_floor_tests.txt

IMPORTANT:
- Source floor databases are READ-ONLY.
- Internal IDs are prefixed by floor to prevent collisions.
- Lift and stair vertical connections are stored separately.
- Routing modes supported:
    lift
    stairs
    either

Run from the main project folder:
    python .\integrate_building.py
"""

from __future__ import annotations

import heapq
import math
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
OUTDIR = ROOT / "integration"
OUTDIR.mkdir(exist_ok=True)

OUT_DB = OUTDIR / "building_navigation.db"
REPORT = OUTDIR / "integration_report.txt"
TEST_REPORT = OUTDIR / "cross_floor_tests.txt"

FLOOR_FOLDERS = [f"f{i}" for i in range(8)]

# Vertical travel costs are routing weights, not physical survey distances.
# They can later be tuned based on measured time.
LIFT_COST_PER_FLOOR = 8.0
STAIR_COST_PER_FLOOR = 12.0


def qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def table_columns(cur: sqlite3.Cursor, table: str) -> List[str]:
    return [row[1] for row in cur.execute(f"PRAGMA table_info({qident(table)})")]


def first_existing(cols, *names):
    for name in names:
        if name in cols:
            return name
    return None


def get_floor_meta(con: sqlite3.Connection):
    cur = con.cursor()
    cols = table_columns(cur, "floors")

    name_col = first_existing(cols, "name", "floor_name")
    if not name_col:
        raise RuntimeError("floors table has neither `name` nor `floor_name`.")

    row = cur.execute(
        f"""
        SELECT floor_id, floor_number, {qident(name_col)}
        FROM floors
        LIMIT 1
        """
    ).fetchone()

    if not row:
        raise RuntimeError("floors table is empty.")

    return str(row[0]), int(row[1]), str(row[2])


def normalize_connector(node_id: str, node_type: str) -> Optional[Tuple[str, int]]:
    """
    Return:
      ("lift", N)
      ("stair", N)
    or None.

    Handles examples:
      LIFT1-G
      LIFT1-F4
      STAIRS1
      STAIRS2-G
      STAIRS3-F7
    """
    u = node_id.upper()
    t = (node_type or "").lower()

    kind = None
    if "LIFT" in u or "ELEVATOR" in u or t in {"lift", "elevator"}:
        kind = "lift"
    elif "STAIR" in u or t in {"stair", "stairs", "staircase"}:
        kind = "stair"
    else:
        return None

    m = re.search(r"(\d+)", u)
    if not m:
        return None

    return kind, int(m.group(1))


def copy_floor_data(
    source_db: Path,
    floor_folder: str,
    dest: sqlite3.Connection,
):
    src = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    s = src.cursor()
    d = dest.cursor()

    floor_id, floor_number, floor_name = get_floor_meta(src)

    d.execute(
        """
        INSERT INTO floors
        (floor_id, floor_number, name, source_folder)
        VALUES (?, ?, ?, ?)
        """,
        (floor_id, floor_number, floor_name, floor_folder),
    )

    # -------------------- locations --------------------
    loc_cols = table_columns(s, "locations")

    loc_code_col = first_existing(loc_cols, "code", "location_id")
    loc_name_col = first_existing(loc_cols, "name", "code", "location_id")
    loc_type_col = first_existing(loc_cols, "type", "location_type")
    searchable_col = first_existing(loc_cols, "searchable")
    public_col = first_existing(loc_cols, "public_access")
    description_col = first_existing(loc_cols, "description")

    location_map = {}

    for row in s.execute("SELECT * FROM locations"):
        old_id = str(row["location_id"])
        new_id = f"{floor_id}:{old_id}"
        location_map[old_id] = new_id

        code = str(row[loc_code_col]) if loc_code_col else old_id
        name = str(row[loc_name_col]) if loc_name_col else code
        loc_type = str(row[loc_type_col]) if loc_type_col and row[loc_type_col] is not None else ""
        searchable = int(row[searchable_col]) if searchable_col and row[searchable_col] is not None else 1
        public_access = int(row[public_col]) if public_col and row[public_col] is not None else searchable
        description = str(row[description_col]) if description_col and row[description_col] is not None else ""

        d.execute(
            """
            INSERT INTO locations
            (location_id, floor_id, original_location_id, code, name,
             type, searchable, public_access, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id, floor_id, old_id, code, name,
                loc_type, searchable, public_access, description
            ),
        )

    # -------------------- nodes --------------------
    node_cols = table_columns(s, "nodes")
    source_svg_col = first_existing(node_cols, "source_svg_id")

    node_map = {}
    connector_records = []

    for row in s.execute("SELECT * FROM nodes"):
        old_node = str(row["node_id"])
        new_node = f"{floor_id}:{old_node}"
        node_map[old_node] = new_node

        node_type = str(row["node_type"]) if row["node_type"] is not None else ""
        x = float(row["x"])
        y = float(row["y"])

        old_loc = None
        if "location_id" in node_cols and row["location_id"] is not None:
            old_loc = str(row["location_id"])

        new_loc = location_map.get(old_loc) if old_loc else None
        source_svg_id = (
            str(row[source_svg_col])
            if source_svg_col and row[source_svg_col] is not None
            else old_node
        )

        connector = normalize_connector(old_node, node_type)
        connector_kind = connector[0] if connector else None
        connector_number = connector[1] if connector else None

        d.execute(
            """
            INSERT INTO nodes
            (node_id, floor_id, original_node_id, node_type, x, y,
             location_id, source_svg_id, connector_kind, connector_number)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_node, floor_id, old_node, node_type, x, y,
                new_loc, source_svg_id, connector_kind, connector_number
            ),
        )

        if connector:
            connector_records.append(
                (connector[0], connector[1], floor_number, floor_id, new_node, old_node)
            )

    # -------------------- horizontal edges --------------------
    edge_cols = table_columns(s, "edges")
    edge_type_col = first_existing(edge_cols, "edge_type")
    accessible_col = first_existing(edge_cols, "accessible")
    bidirectional_col = first_existing(edge_cols, "bidirectional")

    horizontal_count = 0

    for row in s.execute("SELECT * FROM edges"):
        old_edge = str(row["edge_id"])
        from_old = str(row["from_node"])
        to_old = str(row["to_node"])

        if from_old not in node_map or to_old not in node_map:
            raise RuntimeError(
                f"{floor_id}: edge {old_edge} refers to missing node."
            )

        new_edge = f"{floor_id}:{old_edge}"
        edge_type = (
            str(row[edge_type_col])
            if edge_type_col and row[edge_type_col] is not None
            else "horizontal"
        )
        accessible = (
            int(row[accessible_col])
            if accessible_col and row[accessible_col] is not None
            else 1
        )
        bidirectional = (
            int(row[bidirectional_col])
            if bidirectional_col and row[bidirectional_col] is not None
            else 1
        )

        d.execute(
            """
            INSERT INTO edges
            (edge_id, from_node, to_node, distance_m, edge_type,
             travel_mode, is_vertical, accessible, bidirectional,
             from_floor, to_floor, source_edge_id)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
            """,
            (
                new_edge,
                node_map[from_old],
                node_map[to_old],
                float(row["distance_m"]),
                edge_type,
                "walk",
                accessible,
                bidirectional,
                floor_id,
                floor_id,
                old_edge,
            ),
        )
        horizontal_count += 1

    src.close()

    return {
        "floor_id": floor_id,
        "floor_number": floor_number,
        "floor_name": floor_name,
        "nodes": len(node_map),
        "locations": len(location_map),
        "horizontal_edges": horizontal_count,
        "connectors": connector_records,
    }


def create_schema(con: sqlite3.Connection):
    con.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE floors (
            floor_id TEXT PRIMARY KEY,
            floor_number INTEGER NOT NULL,
            name TEXT NOT NULL,
            source_folder TEXT NOT NULL
        );

        CREATE TABLE locations (
            location_id TEXT PRIMARY KEY,
            floor_id TEXT NOT NULL,
            original_location_id TEXT NOT NULL,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            type TEXT,
            searchable INTEGER NOT NULL,
            public_access INTEGER NOT NULL,
            description TEXT,
            FOREIGN KEY(floor_id) REFERENCES floors(floor_id)
        );

        CREATE TABLE nodes (
            node_id TEXT PRIMARY KEY,
            floor_id TEXT NOT NULL,
            original_node_id TEXT NOT NULL,
            node_type TEXT NOT NULL,
            x REAL NOT NULL,
            y REAL NOT NULL,
            location_id TEXT,
            source_svg_id TEXT,
            connector_kind TEXT,
            connector_number INTEGER,
            FOREIGN KEY(floor_id) REFERENCES floors(floor_id),
            FOREIGN KEY(location_id) REFERENCES locations(location_id)
        );

        CREATE TABLE edges (
            edge_id TEXT PRIMARY KEY,
            from_node TEXT NOT NULL,
            to_node TEXT NOT NULL,
            distance_m REAL NOT NULL CHECK(distance_m > 0),
            edge_type TEXT NOT NULL,
            travel_mode TEXT NOT NULL,
            is_vertical INTEGER NOT NULL CHECK(is_vertical IN (0,1)),
            accessible INTEGER NOT NULL CHECK(accessible IN (0,1)),
            bidirectional INTEGER NOT NULL CHECK(bidirectional IN (0,1)),
            from_floor TEXT NOT NULL,
            to_floor TEXT NOT NULL,
            source_edge_id TEXT,
            FOREIGN KEY(from_node) REFERENCES nodes(node_id),
            FOREIGN KEY(to_node) REFERENCES nodes(node_id),
            FOREIGN KEY(from_floor) REFERENCES floors(floor_id),
            FOREIGN KEY(to_floor) REFERENCES floors(floor_id)
        );

        CREATE TABLE vertical_connections (
            connection_id TEXT PRIMARY KEY,
            connector_kind TEXT NOT NULL,
            connector_number INTEGER NOT NULL,
            from_floor TEXT NOT NULL,
            to_floor TEXT NOT NULL,
            from_node TEXT NOT NULL,
            to_node TEXT NOT NULL,
            cost REAL NOT NULL,
            FOREIGN KEY(from_floor) REFERENCES floors(floor_id),
            FOREIGN KEY(to_floor) REFERENCES floors(floor_id),
            FOREIGN KEY(from_node) REFERENCES nodes(node_id),
            FOREIGN KEY(to_node) REFERENCES nodes(node_id)
        );

        CREATE INDEX idx_locations_code
            ON locations(code);

        CREATE INDEX idx_locations_floor
            ON locations(floor_id);

        CREATE INDEX idx_nodes_floor
            ON nodes(floor_id);

        CREATE INDEX idx_edges_from
            ON edges(from_node);

        CREATE INDEX idx_edges_to
            ON edges(to_node);

        CREATE INDEX idx_edges_mode
            ON edges(travel_mode, is_vertical);
        """
    )


def add_vertical_connections(
    con: sqlite3.Connection,
    all_connectors,
):
    """
    Match connector number + kind between adjacent floors only.
    """
    grouped = defaultdict(dict)

    for kind, number, floor_number, floor_id, node_id, original_id in all_connectors:
        key = (kind, number)
        grouped[key][floor_number] = {
            "floor_id": floor_id,
            "node_id": node_id,
            "original_id": original_id,
        }

    d = con.cursor()
    created = []
    missing = []

    for kind in ("lift", "stair"):
        for number in (1, 2, 3):
            key = (kind, number)
            floors = grouped.get(key, {})

            for floor_num in range(0, 7):
                a = floors.get(floor_num)
                b = floors.get(floor_num + 1)

                if not a or not b:
                    missing.append(
                        f"{kind.upper()}{number}: missing F{floor_num}->F{floor_num+1}"
                    )
                    continue

                cost = (
                    LIFT_COST_PER_FLOOR
                    if kind == "lift"
                    else STAIR_COST_PER_FLOOR
                )

                connection_id = (
                    f"V:{kind.upper()}{number}:"
                    f"{a['floor_id']}->{b['floor_id']}"
                )
                edge_id = f"E:{connection_id}"

                d.execute(
                    """
                    INSERT INTO vertical_connections
                    (connection_id, connector_kind, connector_number,
                     from_floor, to_floor, from_node, to_node, cost)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        connection_id, kind, number,
                        a["floor_id"], b["floor_id"],
                        a["node_id"], b["node_id"], cost,
                    ),
                )

                d.execute(
                    """
                    INSERT INTO edges
                    (edge_id, from_node, to_node, distance_m, edge_type,
                     travel_mode, is_vertical, accessible, bidirectional,
                     from_floor, to_floor, source_edge_id)
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?, 1, ?, ?, NULL)
                    """,
                    (
                        edge_id,
                        a["node_id"],
                        b["node_id"],
                        cost,
                        kind,
                        kind,
                        1 if kind == "lift" else 0,
                        a["floor_id"],
                        b["floor_id"],
                    ),
                )

                created.append(connection_id)

    return created, missing


def build_graph(
    con: sqlite3.Connection,
    mode: str,
):
    """
    mode:
      lift   -> horizontal + lift vertical edges
      stairs -> horizontal + stair vertical edges
      either -> horizontal + all vertical edges
    """
    if mode not in {"lift", "stairs", "either"}:
        raise ValueError("mode must be lift, stairs, or either")

    graph = defaultdict(list)
    cur = con.cursor()

    for row in cur.execute(
        """
        SELECT from_node, to_node, distance_m, travel_mode,
               is_vertical, bidirectional
        FROM edges
        """
    ):
        a, b = row[0], row[1]
        weight = float(row[2])
        travel_mode = row[3]
        vertical = bool(row[4])
        bidirectional = bool(row[5])

        allowed = True

        if vertical:
            if mode == "lift":
                allowed = travel_mode == "lift"
            elif mode == "stairs":
                allowed = travel_mode == "stair"
            else:
                allowed = travel_mode in {"lift", "stair"}

        if not allowed:
            continue

        graph[a].append((b, weight))
        if bidirectional:
            graph[b].append((a, weight))

    return graph


def shortest_path(
    con: sqlite3.Connection,
    start: str,
    goal: str,
    mode: str,
):
    graph = build_graph(con, mode)

    if start not in graph or goal not in graph:
        return None

    best = {start: 0.0}
    parent = {}
    queue = [(0.0, start)]

    while queue:
        dist, cur = heapq.heappop(queue)

        if dist != best.get(cur):
            continue

        if cur == goal:
            path = [goal]
            while path[-1] in parent:
                path.append(parent[path[-1]])
            path.reverse()
            return path, dist

        for nxt, weight in graph[cur]:
            nd = dist + weight
            if nd < best.get(nxt, math.inf):
                best[nxt] = nd
                parent[nxt] = cur
                heapq.heappush(queue, (nd, nxt))

    return None


def find_location_node(
    con: sqlite3.Connection,
    floor_id: str,
    code: str,
) -> Optional[str]:
    row = con.execute(
        """
        SELECT n.node_id
        FROM locations l
        JOIN nodes n ON n.location_id = l.location_id
        WHERE l.floor_id = ?
          AND l.code = ?
          AND l.searchable = 1
        ORDER BY n.node_id
        LIMIT 1
        """,
        (floor_id, code),
    ).fetchone()

    if row:
        return row[0]

    # Fallback for databases where node ID equals the room code.
    row = con.execute(
        """
        SELECT node_id
        FROM nodes
        WHERE floor_id = ?
          AND original_node_id = ?
        LIMIT 1
        """,
        (floor_id, code),
    ).fetchone()

    return row[0] if row else None


def find_entrance(con: sqlite3.Connection) -> Optional[str]:
    row = con.execute(
        """
        SELECT node_id
        FROM nodes
        WHERE floor_id = 'G'
          AND (
              UPPER(original_node_id) LIKE '%ENTRANCE%'
              OR LOWER(node_type) = 'entrance'
          )
        ORDER BY node_id
        LIMIT 1
        """
    ).fetchone()
    return row[0] if row else None


def run_cross_floor_tests(con: sqlite3.Connection):
    tests = []

    entrance = find_entrance(con)

    # Use actual searchable examples from multiple floors.
    examples = [
        ("G", None, "F1", "131"),
        ("G", None, "F3", "327"),
        ("G", None, "F4", "434"),
        ("G", None, "F7", "728"),
        ("F2", "227", "F6", "626"),
    ]

    for start_floor, start_code, dest_floor, dest_code in examples:
        if start_floor == "G" and start_code is None:
            start = entrance
        else:
            start = find_location_node(con, start_floor, start_code)

        goal = find_location_node(con, dest_floor, dest_code)

        if not start or not goal:
            tests.append(
                {
                    "label": f"{start_floor}:{start_code} -> {dest_floor}:{dest_code}",
                    "error": "Could not resolve start or goal node.",
                    "modes": {},
                }
            )
            continue

        mode_results = {}

        for mode in ("lift", "stairs", "either"):
            found = shortest_path(con, start, goal, mode)
            mode_results[mode] = found

        tests.append(
            {
                "label": f"{start} -> {goal}",
                "error": None,
                "modes": mode_results,
            }
        )

    return tests


def main():
    if OUT_DB.exists():
        OUT_DB.unlink()

    con = sqlite3.connect(OUT_DB)
    con.execute("PRAGMA foreign_keys = ON")

    try:
        create_schema(con)

        floor_stats = []
        all_connectors = []

        for folder in FLOOR_FOLDERS:
            db = ROOT / folder / "prp_navigation.db"

            if not db.exists():
                raise RuntimeError(f"Missing database: {db}")

            stats = copy_floor_data(db, folder, con)
            floor_stats.append(stats)
            all_connectors.extend(stats["connectors"])

        vertical_created, vertical_missing = add_vertical_connections(
            con, all_connectors
        )

        con.commit()

        # -------- database checks --------
        fk_errors = con.execute("PRAGMA foreign_key_check").fetchall()

        counts = {
            "floors": con.execute("SELECT COUNT(*) FROM floors").fetchone()[0],
            "locations": con.execute("SELECT COUNT(*) FROM locations").fetchone()[0],
            "nodes": con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
            "edges": con.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
            "vertical": con.execute(
                "SELECT COUNT(*) FROM vertical_connections"
            ).fetchone()[0],
        }

        duplicate_nodes = con.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT node_id FROM nodes GROUP BY node_id HAVING COUNT(*) > 1
            )
            """
        ).fetchone()[0]

        duplicate_locations = con.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT location_id FROM locations
                GROUP BY location_id HAVING COUNT(*) > 1
            )
            """
        ).fetchone()[0]

        duplicate_edges = con.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT edge_id FROM edges GROUP BY edge_id HAVING COUNT(*) > 1
            )
            """
        ).fetchone()[0]

        tests = run_cross_floor_tests(con)

        # All modes should find routes for the configured examples.
        failed_tests = []

        test_lines = []

        for test in tests:
            test_lines.append("=" * 70)
            test_lines.append(test["label"])

            if test["error"]:
                failed_tests.append(test["label"])
                test_lines.append("ERROR: " + test["error"])
                continue

            for mode, result in test["modes"].items():
                if result is None:
                    failed_tests.append(f"{test['label']} [{mode}]")
                    test_lines.append(f"{mode.upper():<8}: FAIL")
                else:
                    path, cost = result
                    vertical_nodes = [
                        n for n in path
                        if ":LIFT" in n.upper() or ":STAIR" in n.upper()
                    ]
                    test_lines.append(
                        f"{mode.upper():<8}: PASS | cost={cost:.2f} "
                        f"| nodes={len(path)}"
                    )
                    test_lines.append(
                        "  vertical path: "
                        + (" -> ".join(vertical_nodes) if vertical_nodes else "(none)")
                    )

        TEST_REPORT.write_text(
            "\n".join(test_lines) + "\n",
            encoding="utf-8",
        )

        final_pass = (
            counts["floors"] == 8
            and not fk_errors
            and duplicate_nodes == 0
            and duplicate_locations == 0
            and duplicate_edges == 0
            and not vertical_missing
            and not failed_tests
        )

        stats_lines = []
        for st in floor_stats:
            stats_lines.append(
                f"{st['floor_id']}: "
                f"nodes={st['nodes']}, "
                f"locations={st['locations']}, "
                f"horizontal_edges={st['horizontal_edges']}"
            )

        REPORT.write_text(
f"""PRP E-BLOCK CAMPUSNAV INTEGRATION REPORT
==========================================

SOURCE FLOORS
-------------
{chr(10).join(stats_lines)}

COMBINED COUNTS
---------------
Floors               : {counts['floors']}
Locations            : {counts['locations']}
Nodes                : {counts['nodes']}
Edges total          : {counts['edges']}
Vertical connections : {counts['vertical']}

VERTICAL CONNECTIONS
--------------------
Expected:
3 lifts x 7 adjacent-floor links = 21
3 stairs x 7 adjacent-floor links = 21
Total expected                      = 42

Created: {len(vertical_created)}
Missing: {len(vertical_missing)}

{chr(10).join(vertical_missing) if vertical_missing else 'No missing vertical connectors.'}

INTEGRITY
---------
Foreign-key errors   : {len(fk_errors)}
Duplicate node IDs   : {duplicate_nodes}
Duplicate location IDs: {duplicate_locations}
Duplicate edge IDs   : {duplicate_edges}

ROUTING MODES
-------------
lift   = horizontal walking + lift vertical edges only
stairs = horizontal walking + stair vertical edges only
either = horizontal walking + both lift and stair vertical edges

CROSS-FLOOR TESTS
-----------------
Configured tests failed: {len(failed_tests)}

{chr(10).join(failed_tests) if failed_tests else 'All configured lift/stairs/either routes passed.'}

FINAL RESULT
------------
{'PASS - BUILDING DATABASE READY' if final_pass else 'FAIL - DO NOT USE YET'}

Output database:
{OUT_DB}
""",
            encoding="utf-8",
        )

        print("=" * 72)
        print("PRP E-BLOCK BUILDING INTEGRATION")
        print("=" * 72)
        print(f"Floors               : {counts['floors']}")
        print(f"Locations            : {counts['locations']}")
        print(f"Nodes                : {counts['nodes']}")
        print(f"Edges                : {counts['edges']}")
        print(f"Vertical connections : {counts['vertical']}")
        print()
        print("Lift vertical links  :", con.execute(
            "SELECT COUNT(*) FROM vertical_connections WHERE connector_kind='lift'"
        ).fetchone()[0])
        print("Stair vertical links :", con.execute(
            "SELECT COUNT(*) FROM vertical_connections WHERE connector_kind='stair'"
        ).fetchone()[0])
        print()
        print("Foreign-key errors   :", len(fk_errors))
        print("Missing connectors   :", len(vertical_missing))
        print("Cross-floor failures :", len(failed_tests))
        print()
        print(
            "FINAL RESULT          :",
            "PASS - BUILDING DATABASE READY"
            if final_pass
            else "FAIL - CHECK REPORT"
        )
        print()
        print("Database:", OUT_DB)
        print("Report  :", REPORT)
        print("Tests   :", TEST_REPORT)

        return 0 if final_pass else 1

    except Exception as exc:
        con.rollback()
        print("INTEGRATION ERROR:", exc, file=sys.stderr)
        return 2

    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
