#!/usr/bin/env python3
"""
route_tester.py

Interactive CampusNav route tester for:
    integration/building_navigation.db

Supports:
- Ground-floor entrance as a start
- Searchable room/location start and destination
- Lift-only cross-floor routing
- Stairs-only cross-floor routing
- Same-floor routing
- Floor-by-floor route output

Run:
    python .\route_tester.py
"""

from __future__ import annotations

import heapq
import math
import sqlite3
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "integration" / "building_navigation.db"

VALID_FLOORS = ["G", "F1", "F2", "F3", "F4", "F5", "F6", "F7"]


def connect():
    if not DB.exists():
        raise FileNotFoundError(
            f"Building database not found:\n{DB}\n"
            "Run integrate_building.py first."
        )
    return sqlite3.connect(DB)


def build_graph(con, mode):
    """
    mode = lift or stairs
    Horizontal walking edges are always allowed.
    Only the selected vertical type is allowed.
    """
    graph = defaultdict(list)

    rows = con.execute(
        """
        SELECT from_node, to_node, distance_m,
               travel_mode, is_vertical, bidirectional
        FROM edges
        """
    ).fetchall()

    for from_node, to_node, weight, travel_mode, is_vertical, bidirectional in rows:
        if is_vertical:
            if mode == "lift" and travel_mode != "lift":
                continue
            if mode == "stairs" and travel_mode != "stair":
                continue

        weight = float(weight)
        graph[from_node].append((to_node, weight))

        if bidirectional:
            graph[to_node].append((from_node, weight))

    return graph


def shortest_path(con, start, goal, mode):
    graph = build_graph(con, mode)

    best = {start: 0.0}
    parent = {}
    queue = [(0.0, start)]

    while queue:
        distance, current = heapq.heappop(queue)

        if distance != best.get(current):
            continue

        if current == goal:
            path = [goal]
            while path[-1] in parent:
                path.append(parent[path[-1]])
            path.reverse()
            return path, distance

        for nxt, weight in graph.get(current, []):
            nd = distance + weight
            if nd < best.get(nxt, math.inf):
                best[nxt] = nd
                parent[nxt] = current
                heapq.heappush(queue, (nd, nxt))

    return None, math.inf


def floor_exists(con, floor_id):
    return con.execute(
        "SELECT 1 FROM floors WHERE floor_id = ?",
        (floor_id,),
    ).fetchone() is not None


def list_searchable_locations(con, floor_id):
    return con.execute(
        """
        SELECT code, name, type
        FROM locations
        WHERE floor_id = ?
          AND searchable = 1
        ORDER BY code
        """,
        (floor_id,),
    ).fetchall()


def find_location_node(con, floor_id, code):
    """
    Resolve a user-visible location code to its navigation node.
    Example:
        F4 + 434 -> F4:434-1 (if that is the actual doorway node)
    """
    row = con.execute(
        """
        SELECT n.node_id, l.code, l.name, l.type
        FROM locations l
        JOIN nodes n ON n.location_id = l.location_id
        WHERE l.floor_id = ?
          AND UPPER(l.code) = UPPER(?)
          AND l.searchable = 1
        ORDER BY n.node_id
        LIMIT 1
        """,
        (floor_id, code),
    ).fetchone()

    if row:
        return row

    # Fallback: original node ID itself may equal the entered code.
    row = con.execute(
        """
        SELECT n.node_id,
               COALESCE(l.code, n.original_node_id),
               COALESCE(l.name, n.original_node_id),
               COALESCE(l.type, n.node_type)
        FROM nodes n
        LEFT JOIN locations l ON l.location_id = n.location_id
        WHERE n.floor_id = ?
          AND UPPER(n.original_node_id) = UPPER(?)
        LIMIT 1
        """,
        (floor_id, code),
    ).fetchone()

    return row


def find_ground_entrances(con):
    return con.execute(
        """
        SELECT node_id, original_node_id
        FROM nodes
        WHERE floor_id = 'G'
          AND (
              LOWER(node_type) = 'entrance'
              OR UPPER(original_node_id) LIKE '%ENTRANCE%'
          )
        ORDER BY node_id
        """
    ).fetchall()


def node_info(con, node_id):
    return con.execute(
        """
        SELECT node_id, floor_id, original_node_id,
               node_type, connector_kind, connector_number
        FROM nodes
        WHERE node_id = ?
        """,
        (node_id,),
    ).fetchone()


def edge_info(con, a, b):
    return con.execute(
        """
        SELECT edge_type, travel_mode, is_vertical, distance_m
        FROM edges
        WHERE (from_node = ? AND to_node = ?)
           OR (bidirectional = 1 AND from_node = ? AND to_node = ?)
        LIMIT 1
        """,
        (a, b, b, a),
    ).fetchone()


def choose_floor(prompt):
    while True:
        value = input(prompt).strip().upper()
        if value in VALID_FLOORS:
            return value
        print("Enter one of:", ", ".join(VALID_FLOORS))


def choose_mode():
    while True:
        print("\nHow do you want to change floors?")
        print("1. Lift")
        print("2. Stairs / Steps")
        choice = input("Choose 1 or 2: ").strip()

        if choice == "1":
            return "lift"
        if choice == "2":
            return "stairs"

        print("Invalid choice.")


def print_locations(con, floor_id):
    rows = list_searchable_locations(con, floor_id)

    print(f"\nSearchable locations on {floor_id}:")
    if not rows:
        print("  No searchable locations found.")
        return

    for code, name, loc_type in rows:
        extra = f" - {name}" if name and name != code else ""
        print(f"  {code}{extra} [{loc_type}]")


def choose_start(con):
    floor_id = choose_floor("\nStart floor (G/F1/F2/.../F7): ")

    if floor_id == "G":
        entrances = find_ground_entrances(con)

        if entrances:
            print("\nGround-floor start:")
            print("0. Use an entrance")
            print("1. Use a room/location")
            choice = input("Choose 0 or 1: ").strip()

            if choice == "0":
                if len(entrances) == 1:
                    return entrances[0][0], floor_id, entrances[0][1]

                print("\nAvailable entrances:")
                for i, (_, original) in enumerate(entrances, 1):
                    print(f"{i}. {original}")

                while True:
                    raw = input("Choose entrance number: ").strip()
                    if raw.isdigit() and 1 <= int(raw) <= len(entrances):
                        node_id, original = entrances[int(raw) - 1]
                        return node_id, floor_id, original
                    print("Invalid entrance number.")

    print_locations(con, floor_id)

    while True:
        code = input("Start location code: ").strip()
        row = find_location_node(con, floor_id, code)
        if row:
            return row[0], floor_id, row[1]
        print(f"Location '{code}' was not found/searchable on {floor_id}.")


def choose_destination(con):
    floor_id = choose_floor("\nDestination floor (G/F1/F2/.../F7): ")
    print_locations(con, floor_id)

    while True:
        code = input("Destination location code: ").strip()
        row = find_location_node(con, floor_id, code)
        if row:
            return row[0], floor_id, row[1]
        print(f"Location '{code}' was not found/searchable on {floor_id}.")


def format_route(con, path, mode, start_label, dest_label, cost):
    print("\n" + "=" * 72)
    print("CAMPUSNAV ROUTE")
    print("=" * 72)
    print(f"Start       : {start_label}")
    print(f"Destination : {dest_label}")
    print(f"Mode        : {'LIFT' if mode == 'lift' else 'STAIRS / STEPS'}")
    print(f"Route cost  : {cost:.2f}")
    print()

    current_floor = None
    step_number = 1

    for i, node_id in enumerate(path):
        info = node_info(con, node_id)
        floor_id = info[1]
        original_id = info[2]
        node_type = info[3]

        if floor_id != current_floor:
            print(f"\n--- {floor_id} ---")
            current_floor = floor_id

        if i == 0:
            print(f"{step_number}. START at {original_id}")
            step_number += 1
            continue

        prev = path[i - 1]
        edge = edge_info(con, prev, node_id)

        if edge and edge[2]:  # vertical
            travel_mode = edge[1]

            prev_info = node_info(con, prev)
            from_floor = prev_info[1]
            to_floor = floor_id

            if travel_mode == "lift":
                print(
                    f"{step_number}. Take LIFT "
                    f"from {from_floor} to {to_floor}"
                )
            else:
                print(
                    f"{step_number}. Take STAIRS / STEPS "
                    f"from {from_floor} to {to_floor}"
                )

            step_number += 1
        else:
            if node_type == "room":
                print(f"{step_number}. Reach entrance of {original_id}")
            elif node_type == "lift":
                print(f"{step_number}. Walk to {original_id}")
            elif node_type in {"stair", "stairs", "staircase"}:
                print(f"{step_number}. Walk to {original_id}")
            else:
                print(f"{step_number}. Continue via {original_id}")

            step_number += 1

    print(f"\n✓ Destination reached: {dest_label}")
    print("=" * 72)


def main():
    try:
        con = connect()
    except Exception as exc:
        print("ERROR:", exc)
        return 1

    try:
        print("=" * 72)
        print("PRP E-BLOCK CAMPUSNAV - ROUTE TESTER")
        print("=" * 72)

        start_node, start_floor, start_code = choose_start(con)
        dest_node, dest_floor, dest_code = choose_destination(con)

        if start_floor == dest_floor:
            # Mode does not matter on a same-floor route, but use lift graph
            # because horizontal edges are identical.
            mode = "lift"
            print("\nSame-floor route: Lift/Stairs choice is not required.")
        else:
            mode = choose_mode()

        path, cost = shortest_path(
            con,
            start_node,
            dest_node,
            mode,
        )

        if path is None:
            print("\nNo route could be found.")
            return 2

        start_label = f"{start_code} ({start_floor})"
        dest_label = f"{dest_code} ({dest_floor})"

        format_route(
            con,
            path,
            mode,
            start_label,
            dest_label,
            cost,
        )

        print("\nRaw node path:")
        print(" -> ".join(path))

        return 0

    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
