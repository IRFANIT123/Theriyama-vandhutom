#!/usr/bin/env python3
"""
PRP E Block - Ground Floor A* Route Tester

Usage:
    python test_astar.py ground_floor\prp_navigation.db G29 G31
    python test_astar.py ground_floor\prp_navigation.db ENTRANCE1 G41
    python test_astar.py ground_floor\prp_navigation.db G37 G28

The program:
- reads the extracted SQLite database
- accepts a location ID or node ID as start/destination
- handles rooms with multiple entrance nodes
- runs Dijkstra/A* (A* with a zero heuristic is Dijkstra; here we use
  straight-line distance as an admissible heuristic)
- prints the route, distance and estimated walking time
"""

from __future__ import annotations

import argparse
import heapq
import math
import sqlite3
from pathlib import Path


WALKING_SPEED_M_PER_MIN = 80.0  # 1.33 m/s, approximately 4.8 km/h


def load_database(db_path: Path):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    nodes = {}
    locations = {}
    graph = {}

    for row in con.execute(
        "SELECT node_id, floor_id, node_type, x, y, location_id FROM nodes"
    ):
        nodes[row["node_id"]] = dict(row)
        graph[row["node_id"]] = []

    for row in con.execute(
        """
        SELECT edge_id, from_node, to_node, distance_m,
               edge_type, accessible, bidirectional
        FROM edges
        """
    ):
        a = row["from_node"]
        b = row["to_node"]
        w = float(row["distance_m"])

        if a not in graph or b not in graph:
            raise RuntimeError(
                f"Database error: {row['edge_id']} refers to a missing node."
            )

        graph[a].append((b, w, row["edge_type"], row["accessible"]))

        if row["bidirectional"]:
            graph[b].append((a, w, row["edge_type"], row["accessible"]))

    for row in con.execute(
        """
        SELECT location_id, floor_id, code, name, type,
               searchable, public_access
        FROM locations
        """
    ):
        locations[row["location_id"]] = dict(row)

    con.close()
    return nodes, locations, graph


def heuristic(a, b, nodes):
    """
    Straight-line distance in SVG coordinates converted to metres.
    This is used only as an A* heuristic.
    """
    ax, ay = nodes[a]["x"], nodes[a]["y"]
    bx, by = nodes[b]["x"], nodes[b]["y"]

    svg_distance = math.hypot(ax - bx, ay - by)
    return svg_distance * 0.0264583333333333


def resolve(value, nodes, locations):
    """
    A value may be:
      - a node ID, e.g. ENTRANCE1
      - a location ID, e.g. G37

    A location can have multiple nodes, e.g. G37-1 and G37-2.
    """
    if value in nodes:
        return [value]

    if value in locations:
        matching = [
            node_id
            for node_id, node in nodes.items()
            if node["location_id"] == value
        ]
        if matching:
            return matching

    # Helpful case-insensitive lookup.
    upper = value.upper()

    for node_id in nodes:
        if node_id.upper() == upper:
            return [node_id]

    for location_id in locations:
        if location_id.upper() == upper:
            matching = [
                node_id
                for node_id, node in nodes.items()
                if node["location_id"] == location_id
            ]
            if matching:
                return matching

    return []


def astar(start, goal, nodes, graph):
    open_heap = []
    counter = 0

    g_score = {start: 0.0}
    came_from = {}

    heapq.heappush(
        open_heap,
        (heuristic(start, goal, nodes), counter, start),
    )

    closed = set()

    while open_heap:
        _, _, current = heapq.heappop(open_heap)

        if current in closed:
            continue

        if current == goal:
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            path.reverse()
            return path, g_score[goal]

        closed.add(current)

        for neighbor, weight, edge_type, accessible in graph[current]:
            if neighbor in closed:
                continue

            tentative = g_score[current] + weight

            if tentative < g_score.get(neighbor, float("inf")):
                came_from[neighbor] = current
                g_score[neighbor] = tentative
                counter += 1

                f = tentative + heuristic(neighbor, goal, nodes)

                heapq.heappush(
                    open_heap,
                    (f, counter, neighbor),
                )

    return None, float("inf")


def display_name(node_id, nodes):
    node = nodes[node_id]
    location = node["location_id"]

    if location:
        return location

    return node_id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("start")
    parser.add_argument("destination")
    args = parser.parse_args()

    if not args.database.exists():
        raise SystemExit(f"ERROR: Database not found: {args.database}")

    nodes, locations, graph = load_database(args.database)

    starts = resolve(args.start, nodes, locations)
    goals = resolve(args.destination, nodes, locations)

    if not starts:
        print(f"ERROR: Start '{args.start}' was not found.")
        print("Available locations:")
        for x in sorted(locations):
            print(" ", x)
        return 1

    if not goals:
        print(f"ERROR: Destination '{args.destination}' was not found.")
        print("Available locations:")
        for x in sorted(locations):
            print(" ", x)
        return 1

    best_path = None
    best_distance = float("inf")
    best_start = None
    best_goal = None

    # Try every possible entrance node for locations with multiple nodes.
    for start in starts:
        for goal in goals:
            if start == goal:
                path = [start]
                total = 0.0
            else:
                path, total = astar(start, goal, nodes, graph)

            if path and total < best_distance:
                best_path = path
                best_distance = total
                best_start = start
                best_goal = goal

    if best_path is None:
        print()
        print("NO ROUTE FOUND")
        print("The graph could not connect the selected points.")
        return 2

    print()
    print("=" * 60)
    print("PRP E BLOCK - A* ROUTE TEST")
    print("=" * 60)
    print(f"Start       : {args.start} ({best_start})")
    print(f"Destination : {args.destination} ({best_goal})")
    print(f"Nodes in DB : {len(nodes)}")
    print(f"Route nodes : {len(best_path)}")
    print(f"Distance    : {best_distance:.2f} m")
    print(
        f"Est. walking: "
        f"{best_distance / WALKING_SPEED_M_PER_MIN:.2f} min"
    )
    print()
    print("ROUTE")
    print("-" * 60)

    for i, node_id in enumerate(best_path, start=1):
        print(f"{i:2}. {display_name(node_id, nodes)} [{node_id}]")

    print()
    print("RESULT: A* route found successfully.")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
