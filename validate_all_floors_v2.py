#!/usr/bin/env python3
r"""
validate_all_floors.py

Validates every floor database before PRP E-Block integration.

Expected folder structure:
project/
  floors/
    G/
      prp_navigation.db
    F1/
      prp_navigation.db
    F2/
      prp_navigation.db
    ...

Run in PowerShell:
    python .\scripts\validate_all_floors.py --root .\floors --report .\reports\all_floors_validation.txt

The program does NOT modify any database.
"""

from __future__ import annotations

import argparse
import heapq
import math
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


REQUIRED_TABLES = {"floors", "nodes", "edges", "locations"}

REQUIRED_COLUMNS = {
    "floors": {"floor_id", "floor_number", "name"},
    "nodes": {"node_id", "node_type", "x", "y", "location_id"},
    "edges": {"edge_id", "from_node", "to_node", "distance_m"},
    "locations": {"location_id", "searchable"},
}


@dataclass
class Check:
    label: str
    passed: Optional[bool]  # None = N/A / informational
    detail: str = ""


@dataclass
class FloorResult:
    folder: str
    database: str
    floor_id: str = "UNKNOWN"
    floor_name: str = "UNKNOWN"
    floor_number: Optional[int] = None
    checks: List[Check] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors and all(
            check.passed is not False for check in self.checks
        )


def status_text(check: Check) -> str:
    if check.passed is True:
        return "PASS"
    if check.passed is False:
        return "FAIL"
    return "N/A"


def qident(name: str) -> str:
    # We only use this for SQLite identifiers discovered from SQLite itself.
    return '"' + name.replace('"', '""') + '"'


def list_tables(cur: sqlite3.Cursor) -> Set[str]:
    return {
        row[0]
        for row in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def table_columns(cur: sqlite3.Cursor, table: str) -> Set[str]:
    return {
        row[1]
        for row in cur.execute(
            f"PRAGMA table_info({qident(table)})"
        ).fetchall()
    }


def duplicate_values(
    cur: sqlite3.Cursor, table: str, column: str
) -> List[Tuple[str, int]]:
    sql = f"""
        SELECT {qident(column)}, COUNT(*)
        FROM {qident(table)}
        GROUP BY {qident(column)}
        HAVING COUNT(*) > 1
        ORDER BY COUNT(*) DESC, {qident(column)}
    """
    return cur.execute(sql).fetchall()


def find_database(floor_dir: Path) -> Tuple[Optional[Path], Optional[str]]:
    preferred = floor_dir / "prp_navigation.db"
    if preferred.is_file():
        return preferred, None

    dbs = sorted(
        p for p in floor_dir.glob("*.db")
        if p.is_file()
    )

    if len(dbs) == 1:
        return dbs[0], None
    if not dbs:
        return None, "No .db file found."
    return None, (
        "More than one .db file found. Keep only the final database in "
        "this floor folder or rename the final one to prp_navigation.db: "
        + ", ".join(p.name for p in dbs)
    )


def build_graph(
    cur: sqlite3.Cursor,
    edge_columns: Set[str],
) -> Dict[str, List[Tuple[str, float]]]:
    graph: Dict[str, List[Tuple[str, float]]] = {}

    for (node_id,) in cur.execute("SELECT node_id FROM nodes"):
        graph[node_id] = []

    has_bidirectional = "bidirectional" in edge_columns

    select = "SELECT from_node, to_node, distance_m"
    if has_bidirectional:
        select += ", bidirectional"
    select += " FROM edges"

    for row in cur.execute(select):
        a = row[0]
        b = row[1]
        weight = float(row[2])

        if a not in graph or b not in graph:
            # Broken refs are reported separately.
            continue
        if weight <= 0:
            continue

        graph[a].append((b, weight))

        bidirectional = True
        if has_bidirectional:
            bidirectional = bool(row[3])

        if bidirectional:
            graph[b].append((a, weight))

    return graph


def load_coordinates(
    cur: sqlite3.Cursor,
) -> Dict[str, Tuple[float, float]]:
    coords = {}
    for node_id, x, y in cur.execute(
        "SELECT node_id, x, y FROM nodes"
    ):
        try:
            coords[node_id] = (float(x), float(y))
        except (TypeError, ValueError):
            pass
    return coords


def astar(
    graph: Dict[str, List[Tuple[str, float]]],
    coords: Dict[str, Tuple[float, float]],
    start: str,
    goal: str,
) -> Optional[Tuple[List[str], float]]:
    if start not in graph or goal not in graph:
        return None
    if start == goal:
        return [start], 0.0

    def heuristic(a: str, b: str) -> float:
        # Coordinates on different floors/scales are irrelevant here because
        # this validator works one floor at a time. If coordinates are missing,
        # fall back to Dijkstra (h=0).
        if a not in coords or b not in coords:
            return 0.0
        ax, ay = coords[a]
        bx, by = coords[b]
        # Do NOT assume any metres-per-SVG-unit here. A consistent non-negative
        # heuristic is not guaranteed across independently-created SVGs, so
        # use zero for correctness.
        return 0.0

    best = {start: 0.0}
    parent: Dict[str, str] = {}
    queue = [(heuristic(start, goal), 0.0, start)]

    while queue:
        _, g, current = heapq.heappop(queue)

        if g != best.get(current):
            continue

        if current == goal:
            path = [goal]
            while path[-1] in parent:
                path.append(parent[path[-1]])
            path.reverse()
            return path, g

        for nxt, weight in graph[current]:
            ng = g + weight
            if ng < best.get(nxt, math.inf):
                best[nxt] = ng
                parent[nxt] = current
                heapq.heappush(
                    queue,
                    (ng + heuristic(nxt, goal), ng, nxt)
                )

    return None


def resolve_location_node(
    cur: sqlite3.Cursor,
    location_id: str,
) -> Optional[str]:
    # Preferred: nodes.location_id points to the location.
    row = cur.execute(
        """
        SELECT node_id
        FROM nodes
        WHERE location_id = ?
        ORDER BY CASE WHEN node_id = ? THEN 0 ELSE 1 END, node_id
        LIMIT 1
        """,
        (location_id, location_id),
    ).fetchone()

    if row:
        return row[0]

    # Backward-compatible fallback: node ID itself equals location ID.
    row = cur.execute(
        "SELECT node_id FROM nodes WHERE node_id = ? LIMIT 1",
        (location_id,),
    ).fetchone()
    return row[0] if row else None


def find_nodes_by_kind(
    cur: sqlite3.Cursor,
    kind: str,
) -> List[str]:
    kind_upper = kind.upper()

    if kind_upper == "ENTRANCE":
        return [
            row[0]
            for row in cur.execute(
                """
                SELECT node_id
                FROM nodes
                WHERE UPPER(node_id) LIKE '%ENTRANCE%'
                   OR UPPER(node_type) = 'ENTRANCE'
                ORDER BY node_id
                """
            ).fetchall()
        ]

    if kind_upper == "STAIR":
        return [
            row[0]
            for row in cur.execute(
                """
                SELECT node_id
                FROM nodes
                WHERE LOWER(node_type) IN ('stair','stairs','staircase')
                   OR UPPER(node_id) LIKE '%STAIR%'
                ORDER BY node_id
                """
            ).fetchall()
        ]

    if kind_upper == "LIFT":
        return [
            row[0]
            for row in cur.execute(
                """
                SELECT node_id
                FROM nodes
                WHERE LOWER(node_type) IN ('lift','elevator')
                   OR UPPER(node_id) LIKE '%LIFT%'
                   OR UPPER(node_id) LIKE '%ELEVATOR%'
                ORDER BY node_id
                """
            ).fetchall()
        ]

    raise ValueError(kind)


def is_ground_floor(
    floor_id: str,
    floor_name: str,
    floor_number: Optional[int],
) -> bool:
    if floor_number == 0:
        return True
    text = f"{floor_id} {floor_name}".upper()
    return (
        floor_id.upper() in {"G", "GF", "G0"}
        or "GROUND" in text
    )


def validate_one_floor(floor_dir: Path) -> FloorResult:
    db_path, db_problem = find_database(floor_dir)
    result = FloorResult(
        folder=floor_dir.name,
        database=str(db_path) if db_path else "(not found)",
    )

    if db_problem:
        result.checks.append(Check("Database", False, db_problem))
        result.errors.append(db_problem)
        return result

    assert db_path is not None

    try:
        con = sqlite3.connect(str(db_path))
        con.execute("PRAGMA foreign_keys = ON")
        cur = con.cursor()
        # Force SQLite to actually read from the file.
        cur.execute("SELECT 1").fetchone()
        result.checks.append(Check("Database", True, db_path.name))
    except Exception as exc:
        msg = f"Cannot open database: {exc}"
        result.checks.append(Check("Database", False, msg))
        result.errors.append(msg)
        return result

    try:
        tables = list_tables(cur)

        missing_tables = sorted(REQUIRED_TABLES - tables)
        result.checks.append(
            Check(
                "Required tables",
                not missing_tables,
                "Missing: " + ", ".join(missing_tables)
                if missing_tables else "floors, nodes, edges, locations",
            )
        )
        if missing_tables:
            result.errors.append(
                "Missing required tables: " + ", ".join(missing_tables)
            )
            return result

        # Validate required columns.
        table_cols = {
            table: table_columns(cur, table)
            for table in REQUIRED_TABLES
        }

        bad_columns = []
        for table, required in REQUIRED_COLUMNS.items():
            missing_cols = sorted(required - table_cols[table])
            if missing_cols:
                bad_columns.append(
                    f"{table}: missing {', '.join(missing_cols)}"
                )

        result.checks.append(
            Check(
                "Required columns",
                not bad_columns,
                "; ".join(bad_columns) if bad_columns else "PASS",
            )
        )
        if bad_columns:
            result.errors.extend(bad_columns)
            return result

        # Floor metadata.
        floor_rows = cur.execute(
            """
            SELECT floor_id, floor_number, name
            FROM floors
            ORDER BY display_order, floor_number
            """
            if "display_order" in table_cols["floors"]
            else
            """
            SELECT floor_id, floor_number, name
            FROM floors
            ORDER BY floor_number
            """
        ).fetchall()

        if len(floor_rows) != 1:
            msg = (
                f"Expected exactly 1 floor record, found {len(floor_rows)}."
            )
            result.checks.append(Check("Floor record", False, msg))
            result.errors.append(msg)
            return result

        result.floor_id = str(floor_rows[0][0])
        result.floor_number = (
            int(floor_rows[0][1])
            if floor_rows[0][1] is not None else None
        )
        result.floor_name = str(floor_rows[0][2])

        result.checks.append(
            Check(
                "Floor record",
                True,
                f"{result.floor_id} / {result.floor_name}",
            )
        )

        # Counts.
        node_count = cur.execute(
            "SELECT COUNT(*) FROM nodes"
        ).fetchone()[0]
        edge_count = cur.execute(
            "SELECT COUNT(*) FROM edges"
        ).fetchone()[0]
        location_count = cur.execute(
            "SELECT COUNT(*) FROM locations"
        ).fetchone()[0]

        result.checks.append(
            Check("Nodes", node_count > 0, f"{node_count} found")
        )
        result.checks.append(
            Check("Edges", edge_count > 0, f"{edge_count} found")
        )
        result.checks.append(
            Check(
                "Locations",
                location_count > 0,
                f"{location_count} found",
            )
        )

        if node_count == 0:
            result.errors.append("No nodes found.")
        if edge_count == 0:
            result.errors.append("No edges found.")
        if location_count == 0:
            result.errors.append("No locations found.")

        # Duplicate IDs.
        duplicate_nodes = duplicate_values(
            cur, "nodes", "node_id"
        )
        duplicate_edges = duplicate_values(
            cur, "edges", "edge_id"
        )
        duplicate_locations = duplicate_values(
            cur, "locations", "location_id"
        )

        dup_detail = []
        if duplicate_nodes:
            dup_detail.append(
                "nodes=" + ", ".join(str(x[0]) for x in duplicate_nodes)
            )
        if duplicate_edges:
            dup_detail.append(
                "edges=" + ", ".join(str(x[0]) for x in duplicate_edges)
            )
        if duplicate_locations:
            dup_detail.append(
                "locations="
                + ", ".join(str(x[0]) for x in duplicate_locations)
            )

        result.checks.append(
            Check(
                "Unique IDs",
                not dup_detail,
                "; ".join(dup_detail)
                if dup_detail
                else "node_id, edge_id, location_id unique",
            )
        )
        if dup_detail:
            result.errors.append(
                "Duplicate IDs detected: " + "; ".join(dup_detail)
            )

        # Broken edge references.
        missing_from = [
            row[0]
            for row in cur.execute(
                """
                SELECT e.edge_id
                FROM edges e
                LEFT JOIN nodes n ON e.from_node = n.node_id
                WHERE n.node_id IS NULL
                ORDER BY e.edge_id
                """
            ).fetchall()
        ]

        missing_to = [
            row[0]
            for row in cur.execute(
                """
                SELECT e.edge_id
                FROM edges e
                LEFT JOIN nodes n ON e.to_node = n.node_id
                WHERE n.node_id IS NULL
                ORDER BY e.edge_id
                """
            ).fetchall()
        ]

        broken_edges = sorted(set(missing_from + missing_to))
        result.checks.append(
            Check(
                "Broken edges",
                not broken_edges,
                "0"
                if not broken_edges
                else "IDs: " + ", ".join(broken_edges),
            )
        )
        if broken_edges:
            result.errors.append(
                "Broken edges: " + ", ".join(broken_edges)
            )

        # Foreign-key validation also catches node->location problems.
        fk_errors = cur.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()
        result.checks.append(
            Check(
                "Foreign keys",
                not fk_errors,
                "0 broken references"
                if not fk_errors
                else f"{len(fk_errors)} error(s): {fk_errors[:5]}",
            )
        )
        if fk_errors:
            result.errors.append(
                f"Foreign-key errors: {fk_errors}"
            )

        # Invalid edge distances.
        bad_distances = [
            row[0]
            for row in cur.execute(
                """
                SELECT edge_id
                FROM edges
                WHERE distance_m IS NULL OR distance_m <= 0
                ORDER BY edge_id
                """
            ).fetchall()
        ]

        result.checks.append(
            Check(
                "Edge distances",
                not bad_distances,
                "all > 0"
                if not bad_distances
                else "Invalid: " + ", ".join(bad_distances),
            )
        )
        if bad_distances:
            result.errors.append(
                "Invalid edge distances: "
                + ", ".join(bad_distances)
            )

        # Searchable locations.
        searchable_locations = [
            row[0]
            for row in cur.execute(
                """
                SELECT location_id
                FROM locations
                WHERE searchable = 1
                ORDER BY location_id
                """
            ).fetchall()
        ]

        missing_search_nodes = []
        searchable_node_map = {}

        for location_id in searchable_locations:
            node_id = resolve_location_node(cur, location_id)
            if node_id is None:
                missing_search_nodes.append(location_id)
            else:
                searchable_node_map[location_id] = node_id

        searchable_pass = (
            len(searchable_locations) > 0
            and not missing_search_nodes
        )

        result.checks.append(
            Check(
                "Searchable locations",
                searchable_pass,
                (
                    f"{len(searchable_locations)} searchable; "
                    "all have nodes"
                )
                if searchable_pass
                else (
                    "No searchable locations"
                    if not searchable_locations
                    else
                    "Missing node(s): "
                    + ", ".join(missing_search_nodes)
                ),
            )
        )

        if not searchable_pass:
            result.errors.append(
                "Searchable-location validation failed."
            )

        # Entrances / stairs / lifts.
        entrances = find_nodes_by_kind(cur, "ENTRANCE")
        stairs = find_nodes_by_kind(cur, "STAIR")
        lifts = find_nodes_by_kind(cur, "LIFT")

        ground = is_ground_floor(
            result.floor_id,
            result.floor_name,
            result.floor_number,
        )

        if ground:
            entrance_pass = len(entrances) > 0
            result.checks.append(
                Check(
                    "Entrances",
                    entrance_pass,
                    ", ".join(entrances)
                    if entrances
                    else "Ground floor requires at least one entrance.",
                )
            )
            if not entrance_pass:
                result.errors.append(
                    "Ground floor has no entrance node."
                )
        else:
            result.checks.append(
                Check(
                    "Entrances",
                    None,
                    (
                        ", ".join(entrances)
                        if entrances
                        else "not required on upper floor"
                    ),
                )
            )

        stairs_pass = len(stairs) > 0
        lifts_pass = len(lifts) > 0

        result.checks.append(
            Check(
                "Stairs",
                stairs_pass,
                ", ".join(stairs)
                if stairs
                else "No stair nodes found.",
            )
        )
        result.checks.append(
            Check(
                "Lifts",
                lifts_pass,
                ", ".join(lifts)
                if lifts
                else "No lift nodes found.",
            )
        )

        if not stairs_pass:
            result.errors.append("No stair nodes found.")
        if not lifts_pass:
            result.errors.append("No lift nodes found.")

        # Isolated nodes.
        isolated = [
            row[0]
            for row in cur.execute(
                """
                SELECT n.node_id
                FROM nodes n
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM edges e
                    WHERE e.from_node = n.node_id
                       OR e.to_node = n.node_id
                )
                ORDER BY n.node_id
                """
            ).fetchall()
        ]

        result.checks.append(
            Check(
                "Disconnected nodes",
                not isolated,
                "0"
                if not isolated
                else ", ".join(isolated),
            )
        )

        if isolated:
            result.errors.append(
                "Isolated nodes: " + ", ".join(isolated)
            )

        # Graph + A*.
        graph = build_graph(cur, table_cols["edges"])
        coords = load_coordinates(cur)

        # Anchor: first entrance on ground, otherwise first searchable node.
        anchor = None
        if entrances:
            anchor = entrances[0]
        elif searchable_node_map:
            anchor = next(iter(searchable_node_map.values()))
        elif graph:
            anchor = next(iter(graph))

        route_targets: Dict[str, str] = {}

        for location_id, node_id in searchable_node_map.items():
            route_targets[f"location:{location_id}"] = node_id

        for node_id in stairs:
            route_targets[f"stair:{node_id}"] = node_id

        for node_id in lifts:
            route_targets[f"lift:{node_id}"] = node_id

        if ground:
            for node_id in entrances:
                route_targets[f"entrance:{node_id}"] = node_id

        failed_routes = []
        route_examples = []

        if anchor is None:
            failed_routes.append("No usable A* start node.")
        else:
            for label, target in route_targets.items():
                found = astar(graph, coords, anchor, target)
                if found is None:
                    failed_routes.append(
                        f"{anchor} -> {target} ({label})"
                    )
                elif target != anchor and len(route_examples) < 3:
                    path, distance = found
                    route_examples.append(
                        f"{anchor}->{target} "
                        f"({distance:.2f}, {len(path)} nodes)"
                    )

        astar_pass = not failed_routes and bool(route_targets)

        result.checks.append(
            Check(
                "A* tests",
                astar_pass,
                (
                    f"{len(route_targets)} target(s) reachable"
                    + (
                        "; examples: " + " | ".join(route_examples)
                        if route_examples else ""
                    )
                )
                if astar_pass
                else (
                    "Failed: " + " | ".join(failed_routes[:10])
                    if failed_routes
                    else "No A* targets found."
                ),
            )
        )

        if not astar_pass:
            result.errors.append(
                "A* reachability failed: "
                + " | ".join(failed_routes[:20])
            )

        return result

    except sqlite3.DatabaseError as exc:
        msg = f"SQLite error: {exc}"
        result.errors.append(msg)
        result.checks.append(Check("SQLite validation", False, msg))
        return result

    except Exception as exc:
        msg = f"Unexpected validation error: {exc}"
        result.errors.append(msg)
        result.checks.append(Check("Validation", False, msg))
        return result

    finally:
        con.close()


def format_floor(result: FloorResult) -> str:
    title = (
        result.floor_name.upper()
        if result.floor_name != "UNKNOWN"
        else result.folder.upper()
    )

    lines = [
        "=" * 72,
        title,
        f"Folder   : {result.folder}",
        f"Database : {result.database}",
        "=" * 72,
    ]

    for check in result.checks:
        detail = f" — {check.detail}" if check.detail else ""
        lines.append(
            f"{check.label:<24}: {status_text(check):<4}{detail}"
        )

    if result.errors:
        lines.append("")
        lines.append("FAILURE DETAILS")
        lines.append("-" * 72)
        for error in result.errors:
            lines.append(f"- {error}")

    lines.append("")
    lines.append(
        f"FLOOR RESULT: {'PASS' if result.passed else 'FAIL'}"
    )
    return "\n".join(lines)


def discover_floor_dirs(root: Path) -> List[Path]:
    if not root.is_dir():
        raise FileNotFoundError(
            f"Floor root folder does not exist: {root}"
        )

    # Only validate actual floor folders: f0, f1, ... f7.
    # Ignore project folders such as integration, backend, frontend, reports, etc.
    valid_floor_names = {f"f{i}" for i in range(8)}

    dirs = [
        p for p in sorted(root.iterdir())
        if p.is_dir() and p.name.lower() in valid_floor_names
    ]

    if not dirs:
        raise RuntimeError(
            f"No floor folders found inside: {root}"
        )

    return dirs


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate all PRP E-Block floor SQLite databases."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("floors"),
        help="Folder containing one subfolder per floor.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("reports") / "all_floors_validation.txt",
        help="Text report path.",
    )
    args = parser.parse_args()

    try:
        floor_dirs = discover_floor_dirs(args.root)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    results = [
        validate_one_floor(floor_dir)
        for floor_dir in floor_dirs
    ]

    results.sort(
        key=lambda r: (
            r.floor_number is None,
            r.floor_number if r.floor_number is not None else 10**9,
            r.floor_name,
        )
    )

    floor_sections = [format_floor(r) for r in results]

    passed = sum(r.passed for r in results)
    failed = len(results) - passed

    summary = [
        "",
        "=" * 72,
        "OVERALL RESULT",
        "=" * 72,
        f"Floors checked : {len(results)}",
        f"Floors passed  : {passed}",
        f"Floors failed  : {failed}",
        "",
        (
            "READY FOR INTEGRATION"
            if failed == 0
            else "NOT READY FOR INTEGRATION"
        ),
    ]

    text = "\n\n".join(floor_sections) + "\n" + "\n".join(summary)

    print(text)

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(text, encoding="utf-8")

    print(f"\nReport saved to: {args.report}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
