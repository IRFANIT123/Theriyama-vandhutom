from __future__ import annotations

import heapq
import json
import math
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATABASE_PATH = PROJECT_ROOT / "integration" / "building_navigation.db"
ENTRANCE_CONFIG_PATH = Path(__file__).resolve().parent / "entrances.json"

FLOOR_TO_FOLDER = {
    "G": "f0",
    "F1": "f1",
    "F2": "f2",
    "F3": "f3",
    "F4": "f4",
    "F5": "f5",
    "F6": "f6",
    "F7": "f7",
}

# Outdoor GPS is approximate. The user does NOT need to stand on the exact pin.
ENTRANCE_RADIUS_M = 10.0
VERY_CLOSE_RADIUS_M = 25.0
POOR_GPS_ACCURACY_M = 20.0

EXIT_ALIASES = {
    "EXIT",
    "NEAREST EXIT",
    "LEAVE",
    "LEAVE BUILDING",
    "GO OUT",
    "OUTSIDE",
}

app = FastAPI(
    title="Navora - PRP E Block API",
    description=(
        "Indoor navigation backend for PRP E Block with "
        "exit routing, outdoor nearest-entrance GPS, "
        "blocked connector rerouting, and user-assisted checkpoints."
    ),
    version="3.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------
# DATABASE / FILE HELPERS
# ---------------------------------------------------------------------

def get_connection() -> sqlite3.Connection:
    if not DATABASE_PATH.exists():
        raise RuntimeError(
            "building_navigation.db was not found at: "
            + str(DATABASE_PATH)
        )

    con = sqlite3.connect(str(DATABASE_PATH))
    con.row_factory = sqlite3.Row
    return con


def load_entrance_config() -> dict:
    if not ENTRANCE_CONFIG_PATH.exists():
        raise HTTPException(
            status_code=500,
            detail=(
                "backend/entrances.json was not found. "
                "Place entrances.json beside backend/main.py."
            ),
        )

    try:
        return json.loads(
            ENTRANCE_CONFIG_PATH.read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not read entrances.json: {exc}",
        )


def find_floor_svg(floor_id: str) -> Path:
    floor_id = floor_id.strip().upper()

    if floor_id not in FLOOR_TO_FOLDER:
        raise HTTPException(status_code=404, detail="Unknown floor.")

    folder = PROJECT_ROOT / FLOOR_TO_FOLDER[floor_id]

    if not folder.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Floor folder not found: {folder}",
        )

    svg_files = sorted(folder.glob("*.svg"))

    if not svg_files:
        raise HTTPException(
            status_code=404,
            detail=f"No SVG file found inside {folder.name}.",
        )

    preferred = [
        p for p in svg_files
        if "final" in p.name.lower() or "map" in p.name.lower()
    ]

    return preferred[0] if preferred else svg_files[0]


# ---------------------------------------------------------------------
# LOCATION / ENTRANCE HELPERS
# ---------------------------------------------------------------------

def resolve_location_node(
    con: sqlite3.Connection,
    floor_id: str,
    code: str,
) -> Optional[sqlite3.Row]:

    floor_id = floor_id.strip()
    code = code.strip()

    row = con.execute(
        """
        SELECT
            n.node_id,
            n.floor_id,
            n.original_node_id,
            n.node_type,
            n.x,
            n.y,
            l.location_id,
            l.code,
            l.name,
            l.type
        FROM locations l
        JOIN nodes n
          ON n.location_id = l.location_id
        WHERE UPPER(l.floor_id) = UPPER(?)
          AND UPPER(l.code) = UPPER(?)
          AND l.searchable = 1
        ORDER BY n.node_id
        LIMIT 1
        """,
        (floor_id, code),
    ).fetchone()

    if row:
        return row

    row = con.execute(
        """
        SELECT
            n.node_id,
            n.floor_id,
            n.original_node_id,
            n.node_type,
            n.x,
            n.y,
            NULL AS location_id,
            n.original_node_id AS code,
            n.original_node_id AS name,
            n.node_type AS type
        FROM nodes n
        WHERE UPPER(n.floor_id) = UPPER(?)
          AND UPPER(n.original_node_id) = UPPER(?)
        LIMIT 1
        """,
        (floor_id, code),
    ).fetchone()

    return row


def get_entrance_rows(con: sqlite3.Connection) -> List[sqlite3.Row]:
    return con.execute(
        """
        SELECT
            node_id,
            floor_id,
            original_node_id,
            node_type,
            x,
            y
        FROM nodes
        WHERE floor_id = 'G'
          AND (
              LOWER(node_type) = 'entrance'
              OR UPPER(original_node_id) LIKE '%ENTRANCE%'
          )
        ORDER BY original_node_id
        """
    ).fetchall()


def friendly_entrance_label(original_node_id: str) -> str:
    config = load_entrance_config()
    item = config.get(original_node_id, {})
    return item.get("label", original_node_id)


# ---------------------------------------------------------------------
# GPS HELPERS
# ---------------------------------------------------------------------

def haversine_m(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    radius = 6371000.0

    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)

    a = (
        math.sin(dp / 2) ** 2
        + math.cos(p1)
        * math.cos(p2)
        * math.sin(dl / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius * c


def entrance_distance_results(
    latitude: float,
    longitude: float,
) -> List[dict]:
    config = load_entrance_config()
    results = []

    for node_id, item in config.items():
        entrance_lat = float(item["latitude"])
        entrance_lon = float(item["longitude"])

        distance_m = haversine_m(
            latitude,
            longitude,
            entrance_lat,
            entrance_lon,
        )

        results.append(
            {
                "node_id": node_id,
                "label": item.get("label", node_id),
                "latitude": entrance_lat,
                "longitude": entrance_lon,
                "distance_m": round(distance_m, 1),
            }
        )

    results.sort(key=lambda x: x["distance_m"])
    return results


# ---------------------------------------------------------------------
# BLOCKED CONNECTOR HELPERS
# ---------------------------------------------------------------------

def canonical_block_token(value: str) -> str:
    value = value.strip().upper()
    value = value.replace("STAIRS", "STAIR")

    return "".join(
        ch for ch in value
        if ch.isalnum()
    )


def normalize_blocked(
    blocked: Optional[List[str]],
) -> Set[str]:
    output: Set[str] = set()

    if not blocked:
        return output

    for item in blocked:
        for part in item.split(","):
            token = canonical_block_token(part)
            if token:
                output.add(token)

    return output


def identifier_matches_block(
    identifier: str,
    blocked_tokens: Set[str],
) -> bool:
    if not blocked_tokens:
        return False

    target = canonical_block_token(identifier)

    for token in blocked_tokens:
        if token and token in target:
            return True

    return False


# ---------------------------------------------------------------------
# GRAPH / ROUTING
# ---------------------------------------------------------------------

def floor_level(floor_id: str) -> int:
    """Return the numeric building level used to price direct stair travel."""

    token = str(floor_id or "").strip().upper()
    if token in {"G", "GF", "GROUND"}:
        return 0
    if token.startswith("F") and token[1:].isdigit():
        return int(token[1:])
    return 0

def build_graph(
    con: sqlite3.Connection,
    mode: str,
    blocked_tokens: Optional[Set[str]] = None,
    allow_vertical: bool = True,
    walking_floors: Optional[Set[str]] = None,
) -> Dict[str, List[Tuple[str, float]]] :

    if mode not in {"lift", "stairs"}:
        raise ValueError("mode must be 'lift' or 'stairs'")

    blocked_tokens = blocked_tokens or set()

    graph: Dict[str, List[Tuple[str, float]]] = defaultdict(list)

    rows = con.execute(
        """
        SELECT
            edge_id,
            from_node,
            to_node,
            distance_m,
            travel_mode,
            is_vertical,
            bidirectional,
            from_floor,
            to_floor
        FROM edges
        """
    ).fetchall()

    for row in rows:
        edge_id = row["edge_id"]
        a = row["from_node"]
        b = row["to_node"]
        weight = float(row["distance_m"])
        travel_mode = row["travel_mode"]
        is_vertical = bool(row["is_vertical"])
        bidirectional = bool(row["bidirectional"])
        from_floor = row["from_floor"]
        to_floor = row["to_floor"]

        # A blocked lift/stair means the connector cannot be USED to
        # change floors. Keep normal horizontal walking edges around the
        # lift/stair lobby so the corridor graph itself is not cut apart.
        #
        # Example: blocked=LIFT3 removes only vertical Lift 3 travel edges;
        # walking past/near LIFT3 on the same floor remains possible.
        if is_vertical and (
            identifier_matches_block(a, blocked_tokens)
            or identifier_matches_block(b, blocked_tokens)
        ):
            continue

        if is_vertical and not allow_vertical:
            continue

        # On a cross-floor stair route, intermediate floors are transit-only.
        # Do not let Dijkstra leave one staircase, walk across an intermediate
        # corridor, and enter another staircase just to shave a few metres.
        if (
            not is_vertical
            and walking_floors is not None
            and (
                from_floor not in walking_floors
                or to_floor not in walking_floors
            )
        ):
            continue

        if is_vertical:
            if mode == "lift" and travel_mode != "lift":
                continue

            if mode == "stairs" and travel_mode != "stair":
                continue

        graph[a].append((b, weight))

        if bidirectional:
            graph[b].append((a, weight))

    # A staircase is one continuous vertical connector. The imported graph
    # stores separate U/D landings on every floor; following only those raw
    # edges incorrectly forces a corridor walk across each intermediate floor.
    # Add direct, in-stair links between every pair of floors belonging to the
    # same numbered staircase. Horizontal movement is then needed only on the
    # starting and destination floors.
    if mode == "stairs" and allow_vertical:
        stair_nodes = con.execute(
            """
            SELECT node_id, floor_id, connector_number
            FROM nodes
            WHERE LOWER(COALESCE(connector_kind, '')) = 'stair'
              AND connector_number IS NOT NULL
            ORDER BY connector_number, floor_id, node_id
            """
        ).fetchall()
        by_stair: Dict[str, List[sqlite3.Row]] = defaultdict(list)
        for node in stair_nodes:
            by_stair[str(node["connector_number"])].append(node)

        for number, connector_nodes in by_stair.items():
            connector_id = "STAIRS" + number
            if identifier_matches_block(connector_id, blocked_tokens):
                continue
            for index, a_node in enumerate(connector_nodes):
                if identifier_matches_block(a_node["node_id"], blocked_tokens):
                    continue
                for b_node in connector_nodes[index + 1:]:
                    if a_node["floor_id"] == b_node["floor_id"]:
                        continue
                    if identifier_matches_block(b_node["node_id"], blocked_tokens):
                        continue
                    floor_delta = abs(
                        floor_level(a_node["floor_id"])
                        - floor_level(b_node["floor_id"])
                    )
                    weight = max(1, floor_delta) * 3.5
                    graph[a_node["node_id"]].append((b_node["node_id"], weight))
                    graph[b_node["node_id"]].append((a_node["node_id"], weight))

    return graph


def shortest_path(
    con: sqlite3.Connection,
    start_node: str,
    goal_node: str,
    mode: str,
    blocked_tokens: Optional[Set[str]] = None,
    allow_vertical: bool = True,
) -> Tuple[Optional[List[str]], float]:

    endpoint_floors = con.execute(
        """
        SELECT node_id, floor_id
        FROM nodes
        WHERE node_id IN (?, ?)
        """,
        (start_node, goal_node),
    ).fetchall()
    floor_by_node = {row["node_id"]: row["floor_id"] for row in endpoint_floors}
    start_floor = floor_by_node.get(start_node)
    goal_floor = floor_by_node.get(goal_node)
    walking_floors = (
        {start_floor, goal_floor}
        if start_floor and goal_floor and start_floor != goal_floor
        else None
    )

    graph = build_graph(
        con,
        mode,
        blocked_tokens=blocked_tokens,
        allow_vertical=allow_vertical,
        walking_floors=walking_floors,
    )

    best: Dict[str, float] = {start_node: 0.0}
    parent: Dict[str, str] = {}
    queue: List[Tuple[float, str]] = [(0.0, start_node)]

    while queue:
        current_cost, current = heapq.heappop(queue)

        if current_cost != best.get(current):
            continue

        if current == goal_node:
            path = [goal_node]

            while path[-1] in parent:
                path.append(parent[path[-1]])

            path.reverse()
            return path, current_cost

        for nxt, weight in graph.get(current, []):
            new_cost = current_cost + weight

            if new_cost < best.get(nxt, math.inf):
                best[nxt] = new_cost
                parent[nxt] = current
                heapq.heappush(
                    queue,
                    (new_cost, nxt),
                )

    return None, math.inf


def get_node_info(
    con: sqlite3.Connection,
    node_id: str,
) -> sqlite3.Row:

    row = con.execute(
        """
        SELECT
            node_id,
            floor_id,
            original_node_id,
            node_type,
            x,
            y,
            connector_kind,
            connector_number
        FROM nodes
        WHERE node_id = ?
        """,
        (node_id,),
    ).fetchone()

    if not row:
        raise RuntimeError("Node not found: " + node_id)

    return row


def get_edge_info(
    con: sqlite3.Connection,
    a: str,
    b: str,
) -> Optional[dict]:

    row = con.execute(
        """
        SELECT
            edge_type,
            travel_mode,
            is_vertical,
            distance_m
        FROM edges
        WHERE
            (from_node = ? AND to_node = ?)
            OR
            (bidirectional = 1 AND from_node = ? AND to_node = ?)
        LIMIT 1
        """,
        (a, b, b, a),
    ).fetchone()

    if row:
        return row

    # Mirror the virtual continuous-stair links created by build_graph so
    # route instructions, checkpoints, and distance calculations recognize
    # a direct multi-floor stair segment as a vertical transition.
    nodes = con.execute(
        """
        SELECT node_id, floor_id, connector_kind, connector_number
        FROM nodes
        WHERE node_id IN (?, ?)
        """,
        (a, b),
    ).fetchall()
    if len(nodes) != 2:
        return None

    first, second = nodes
    first_kind = str(first["connector_kind"] or "").lower()
    second_kind = str(second["connector_kind"] or "").lower()
    if (
        first_kind == "stair"
        and second_kind == "stair"
        and str(first["connector_number"]) == str(second["connector_number"])
        and first["floor_id"] != second["floor_id"]
    ):
        floor_delta = abs(
            floor_level(first["floor_id"])
            - floor_level(second["floor_id"])
        )
        return {
            "edge_type": "continuous_stair",
            "travel_mode": "stair",
            "is_vertical": 1,
            "distance_m": max(1, floor_delta) * 3.5,
        }

    return None


def node_used_for_vertical_transition(
    con: sqlite3.Connection,
    path: List[str],
    index: int,
) -> bool:
    """True only when this route actually changes floors at this node."""

    if index > 0:
        edge = get_edge_info(
            con,
            path[index - 1],
            path[index],
        )
        if edge and bool(edge["is_vertical"]):
            return True

    if index < len(path) - 1:
        edge = get_edge_info(
            con,
            path[index],
            path[index + 1],
        )
        if edge and bool(edge["is_vertical"]):
            return True

    return False


# ---------------------------------------------------------------------
# CHECKPOINT HELPERS
# ---------------------------------------------------------------------

def nearest_landmark(
    con: sqlite3.Connection,
    floor_id: str,
    x: float,
    y: float,
) -> Optional[dict]:

    rows = con.execute(
        """
        SELECT
            l.code,
            l.name,
            l.type,
            n.x,
            n.y
        FROM locations l
        JOIN nodes n
          ON n.location_id = l.location_id
        WHERE l.floor_id = ?
          AND l.searchable = 1
        """,
        (floor_id,),
    ).fetchall()

    if not rows:
        return None

    scale_row = con.execute(
        """
        SELECT meters_per_svg_unit
        FROM floor_maps
        WHERE floor_id = ?
        LIMIT 1
        """,
        (floor_id,),
    ).fetchone()

    scale = 1.0
    if (
        scale_row
        and scale_row["meters_per_svg_unit"] is not None
    ):
        scale = float(scale_row["meters_per_svg_unit"])

    best = None

    for row in rows:
        dx = float(row["x"]) - x
        dy = float(row["y"]) - y
        distance_m = math.hypot(dx, dy) * scale

        if best is None or distance_m < best["distance_m"]:
            best = {
                "code": row["code"],
                "name": row["name"],
                "type": row["type"],
                "distance_m": distance_m,
            }

    # Only call it a landmark if it is reasonably close to the route point.
    if best and best["distance_m"] <= 8.0:
        best["distance_m"] = round(best["distance_m"], 1)
        return best

    return None


def build_checkpoints(
    con: sqlite3.Connection,
    path: List[str],
    start_code: str,
    destination_code: str,
) -> List[dict]:

    if not path:
        return []

    important: Set[int] = {0, len(path) - 1}

    for index, node_id in enumerate(path):
        node = get_node_info(con, node_id)
        node_type = (node["node_type"] or "").lower()

        if (
            node_type in {"lift", "stair", "stairs", "staircase"}
            and node_used_for_vertical_transition(con, path, index)
        ):
            important.add(index)

        if index > 0:
            edge = get_edge_info(
                con,
                path[index - 1],
                node_id,
            )

            if edge and bool(edge["is_vertical"]):
                important.add(index - 1)
                important.add(index)

    # Indoor progress is user-confirmed point by point. Keep every graph node
    # in the checkpoint sequence so a bend can never disappear between two
    # sampled dots. The frontend keeps the overview calm by emphasizing the
    # current point, the next point, every genuine turn, and the destination.
    chosen_indices = list(range(len(path)))

    # Cumulative path distance for progress percentage.
    cumulative = [0.0]

    for index in range(1, len(path)):
        edge = get_edge_info(
            con,
            path[index - 1],
            path[index],
        )

        distance = (
            float(edge["distance_m"])
            if edge
            else 0.0
        )

        cumulative.append(
            cumulative[-1] + distance
        )

    total = cumulative[-1]

    output = []

    for checkpoint_number, path_index in enumerate(
        chosen_indices,
        start=1,
    ):
        node = get_node_info(
            con,
            path[path_index],
        )

        floor_id = node["floor_id"]
        node_type = (node["node_type"] or "").lower()
        x = float(node["x"])
        y = float(node["y"])
        turn_direction = "straight"
        turn_angle_degrees = 0.0

        if 0 < path_index < len(path) - 1:
            previous_node = get_node_info(con, path[path_index - 1])
            next_node = get_node_info(con, path[path_index + 1])
            if (
                previous_node["floor_id"] == floor_id
                and next_node["floor_id"] == floor_id
            ):
                incoming_x = x - float(previous_node["x"])
                incoming_y = y - float(previous_node["y"])
                outgoing_x = float(next_node["x"]) - x
                outgoing_y = float(next_node["y"]) - y
                incoming_length = math.hypot(incoming_x, incoming_y)
                outgoing_length = math.hypot(outgoing_x, outgoing_y)
                if incoming_length > 0.001 and outgoing_length > 0.001:
                    cosine = (
                        incoming_x * outgoing_x
                        + incoming_y * outgoing_y
                    ) / (incoming_length * outgoing_length)
                    turn_angle_degrees = math.degrees(
                        math.acos(max(-1.0, min(1.0, cosine)))
                    )
                    if turn_angle_degrees >= 28.0:
                        cross = incoming_x * outgoing_y - incoming_y * outgoing_x
                        # SVG coordinates grow downward, so a positive cross
                        # product is a clockwise/right-hand turn on the map.
                        turn_direction = "right" if cross > 0 else "left"
            else:
                turn_direction = "floor_change"

        if path_index == 0:
            label = f"Start: {start_code}"

        elif path_index == len(path) - 1:
            label = f"Destination: {destination_code}"

        elif (
            node_type == "lift"
            and node_used_for_vertical_transition(con, path, path_index)
        ):
            number = node["connector_number"]
            label = (
                f"Lift {number}"
                if number is not None
                else "Lift"
            )

        elif (
            node_type in {"stair", "stairs", "staircase"}
            and node_used_for_vertical_transition(con, path, path_index)
        ):
            number = node["connector_number"]
            label = (
                f"Staircase {number}"
                if number is not None
                else "Staircase"
            )

        else:
            landmark = nearest_landmark(
                con,
                floor_id,
                x,
                y,
            )

            if landmark:
                label = "Near " + str(landmark["code"])
            else:
                label = "Route checkpoint"

        progress = (
            100.0
            if total <= 0
            else cumulative[path_index] / total * 100.0
        )

        output.append(
            {
                "checkpoint": checkpoint_number,
                "path_index": path_index,
                "node_id": node["node_id"],
                "node_type": node_type,
                "floor_id": floor_id,
                "x": x,
                "y": y,
                "label": label,
                "turn_direction": turn_direction,
                "turn_angle_degrees": round(turn_angle_degrees, 1),
                "is_turn": turn_direction in {"left", "right"},
                "progress_percent": round(progress, 1),
                "remaining_distance_m": round(
                    max(0.0, total - cumulative[path_index]),
                    2,
                ),
            }
        )

    return output


# ---------------------------------------------------------------------
# ROUTE RESPONSE
# ---------------------------------------------------------------------

def build_route_response(
    con: sqlite3.Connection,
    path: List[str],
    total_cost: float,
    mode: str,
    start_code: str,
    destination_code: str,
    blocked_tokens: Optional[Set[str]] = None,
) -> dict:

    floors: List[str] = []
    floor_routes: Dict[str, List[dict]] = {}
    instructions: List[dict] = []

    blocked_tokens = blocked_tokens or set()

    for index, node_id in enumerate(path):
        node = get_node_info(
            con,
            node_id,
        )

        floor_id = node["floor_id"]
        original_id = node["original_node_id"]
        node_type = node["node_type"]

        if floor_id not in floors:
            floors.append(floor_id)

        floor_routes.setdefault(
            floor_id,
            [],
        ).append(
            {
                "node_id": node_id,
                "original_node_id": original_id,
                "node_type": node_type,
                "x": float(node["x"]),
                "y": float(node["y"]),
            }
        )

        if index == 0:
            instructions.append(
                {
                    "type": "start",
                    "floor": floor_id,
                    "text": "Start at " + start_code,
                }
            )
            continue

        previous_id = path[index - 1]
        previous_node = get_node_info(
            con,
            previous_id,
        )
        edge = get_edge_info(
            con,
            previous_id,
            node_id,
        )

        if edge and bool(edge["is_vertical"]):
            if edge["travel_mode"] == "lift":
                text = (
                    "Take the lift from "
                    + previous_node["floor_id"]
                    + " to "
                    + floor_id
                )
                instruction_type = "lift"
            else:
                text = (
                    "Take the stairs from "
                    + previous_node["floor_id"]
                    + " to "
                    + floor_id
                )
                instruction_type = "stairs"

            instructions.append(
                {
                    "type": instruction_type,
                    "from_floor": previous_node["floor_id"],
                    "to_floor": floor_id,
                    "text": text,
                }
            )

        elif (
            node_type in {"lift", "stair", "stairs", "staircase"}
            and index != len(path) - 1
            and node_used_for_vertical_transition(con, path, index)
        ):
            label = (
                "Lift"
                if node_type == "lift"
                else "Staircase"
            )

            number = node["connector_number"]

            if number is not None:
                label += " " + str(number)

            instructions.append(
                {
                    "type": "connector",
                    "floor": floor_id,
                    "text": "Proceed to " + label,
                }
            )

    # Always provide a clear final destination instruction.
    final_node = get_node_info(
        con,
        path[-1],
    )

    if destination_code.upper() in EXIT_ALIASES:
        destination_text = "Exit the building"
        destination_type = "exit"
    else:
        destination_text = (
            "Reach " + destination_code
        )
        destination_type = "destination"

    instructions.append(
        {
            "type": destination_type,
            "floor": final_node["floor_id"],
            "text": destination_text,
        }
    )

    cleaned = []

    for instruction in instructions:
        if (
            not cleaned
            or instruction["text"] != cleaned[-1]["text"]
        ):
            cleaned.append(instruction)

    checkpoints = build_checkpoints(
        con,
        path,
        start_code,
        destination_code,
    )

    return {
        "start": start_code,
        "destination": destination_code,
        "mode": mode,
        "total_cost": round(total_cost, 2),
        "floors": floors,
        "instructions": cleaned,
        "floor_routes": floor_routes,
        "checkpoints": checkpoints,
        "blocked": sorted(blocked_tokens),
        "raw_node_path": path,
    }


def best_exit_route(
    con: sqlite3.Connection,
    start_node: str,
    mode: str,
    blocked_tokens: Optional[Set[str]] = None,
) -> Tuple[Optional[List[str]], float, Optional[sqlite3.Row]]:

    best_path = None
    best_cost = math.inf
    best_exit = None

    for exit_row in get_entrance_rows(con):
        path, cost = shortest_path(
            con,
            start_node,
            exit_row["node_id"],
            mode,
            blocked_tokens=blocked_tokens,
        )

        if path is not None and cost < best_cost:
            best_path = path
            best_cost = cost
            best_exit = exit_row

    return best_path, best_cost, best_exit


# ---------------------------------------------------------------------
# API ENDPOINTS
# ---------------------------------------------------------------------

@app.get("/")
def home():
    return {
        "project": "Navora - PRP E Block",
        "status": "running",
        "database": "building_navigation.db",
        "output_style": "2.5D",
        "route_modes": ["lift", "stairs"],
        "features": [
            "nearest outdoor entrance",
            "entrance and exit support",
            "nearest exit routing",
            "blocked lift/stair rerouting",
            "user-assisted progress checkpoints",
        ],
        "api_version": "3.3.0",
    }


@app.get("/health")
def health():
    try:
        con = get_connection()

        floors = con.execute(
            "SELECT COUNT(*) AS count FROM floors"
        ).fetchone()["count"]

        nodes = con.execute(
            "SELECT COUNT(*) AS count FROM nodes"
        ).fetchone()["count"]

        edges = con.execute(
            "SELECT COUNT(*) AS count FROM edges"
        ).fetchone()["count"]

        con.close()

        entrance_config_ok = ENTRANCE_CONFIG_PATH.exists()

        return {
            "status": "ok",
            "floors": floors,
            "nodes": nodes,
            "edges": edges,
            "entrance_gps_config": entrance_config_ok,
            "entrance_radius_m": ENTRANCE_RADIUS_M,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


@app.get("/floors")
def floors():
    con = get_connection()

    rows = con.execute(
        """
        SELECT floor_id, floor_number, name
        FROM floors
        ORDER BY floor_number
        """
    ).fetchall()

    con.close()

    return [dict(row) for row in rows]


@app.get("/maps")
def maps():
    output = []

    for floor_id in FLOOR_TO_FOLDER:
        try:
            svg = find_floor_svg(floor_id)

            output.append(
                {
                    "floor_id": floor_id,
                    "file_name": svg.name,
                    "url": f"/map/{floor_id}",
                }
            )

        except HTTPException:
            output.append(
                {
                    "floor_id": floor_id,
                    "file_name": None,
                    "url": None,
                }
            )

    return output


@app.get("/map/{floor_id}")
def floor_map(floor_id: str):
    svg = find_floor_svg(floor_id)

    return FileResponse(
        path=str(svg),
        media_type="image/svg+xml",
        filename=svg.name,
    )


@app.get("/locations")
def locations(
    floor_id: str = Query(
        ...,
        description="Example: G, F1, F4",
    ),
    include_non_searchable: bool = Query(
        False,
        description="Include blueprint rooms that do not have a routable navigation node.",
    ),
):
    con = get_connection()

    rows = con.execute(
        """
        SELECT
            location_id,
            floor_id,
            code,
            name,
            type,
            searchable
        FROM locations
        WHERE UPPER(floor_id) = UPPER(?)
          AND (? = 1 OR searchable = 1)
        ORDER BY code
        """,
        (floor_id.strip(), int(include_non_searchable)),
    ).fetchall()

    con.close()

    return [dict(row) for row in rows]


@app.get("/search")
def search(
    q: str = Query(..., min_length=1),
):
    con = get_connection()

    try:
        q_clean = q.strip()
        q_upper = q_clean.upper()
        pattern = "%" + q_clean + "%"

        output = []

        # "exit" is a first-class searchable destination.
        if (
            "EXIT" in q_upper
            or "LEAVE" in q_upper
            or "OUTSIDE" in q_upper
        ):
            output.append(
                {
                    "location_id": "VIRTUAL-NEAREST-EXIT",
                    "floor_id": "G",
                    "code": "EXIT",
                    "name": "Nearest Exit",
                    "type": "exit",
                    "virtual": True,
                }
            )

            for entrance in get_entrance_rows(con):
                output.append(
                    {
                        "location_id": (
                            "EXIT-" + entrance["original_node_id"]
                        ),
                        "floor_id": "G",
                        "code": entrance["original_node_id"],
                        "name": (
                            friendly_entrance_label(
                                entrance["original_node_id"]
                            )
                            + " / Exit"
                        ),
                        "type": "exit",
                        "virtual": True,
                    }
                )

        rows = con.execute(
            """
            SELECT
                location_id,
                floor_id,
                code,
                name,
                type
            FROM locations
            WHERE searchable = 1
              AND (
                  code LIKE ?
                  OR name LIKE ?
              )
            ORDER BY floor_id, code
            LIMIT 50
            """,
            (pattern, pattern),
        ).fetchall()

        output.extend(
            dict(row)
            for row in rows
        )

        return output

    finally:
        con.close()


@app.get("/entrances")
def entrances():
    con = get_connection()

    try:
        config = load_entrance_config()
        output = []

        for row in get_entrance_rows(con):
            item = dict(row)
            gps = config.get(
                row["original_node_id"],
                {},
            )

            item["label"] = gps.get(
                "label",
                row["original_node_id"],
            )
            item["acts_as_exit"] = True
            item["latitude"] = gps.get("latitude")
            item["longitude"] = gps.get("longitude")

            output.append(item)

        return output

    finally:
        con.close()


@app.get("/exits")
def exits():
    con = get_connection()

    try:
        output = [
            {
                "code": "EXIT",
                "name": "Nearest Exit",
                "type": "exit",
                "automatic": True,
            }
        ]

        for row in get_entrance_rows(con):
            output.append(
                {
                    "code": row["original_node_id"],
                    "name": (
                        friendly_entrance_label(
                            row["original_node_id"]
                        )
                        + " / Exit"
                    ),
                    "type": "exit",
                    "automatic": False,
                }
            )

        return output

    finally:
        con.close()


@app.get("/nearest-entrance")
def nearest_entrance(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    accuracy_m: Optional[float] = Query(
        None,
        ge=0,
        description="Optional browser GPS accuracy in metres.",
    ),
):
    results = entrance_distance_results(
        latitude,
        longitude,
    )

    if not results:
        raise HTTPException(
            status_code=500,
            detail="No entrance GPS coordinates configured.",
        )

    nearest = results[0]
    distance = float(nearest["distance_m"])

    if distance <= ENTRANCE_RADIUS_M:
        proximity = "near_entrance"
        message = (
            "You are near this entrance. "
            "Indoor navigation can start here."
        )

    elif distance <= VERY_CLOSE_RADIUS_M:
        proximity = "very_close"
        message = (
            "You are very close to this entrance. "
            "Walk toward it to start indoor navigation."
        )

    else:
        proximity = "approach"
        message = (
            "This is the nearest building entrance. "
            "Continue toward it."
        )

    approximate = (
        accuracy_m is not None
        and accuracy_m > POOR_GPS_ACCURACY_M
    )

    return {
        "nearest_entrance": nearest,
        "all_entrances": results,
        "proximity": proximity,
        "within_entrance_radius": (
            distance <= ENTRANCE_RADIUS_M
        ),
        "entrance_radius_m": ENTRANCE_RADIUS_M,
        "gps_accuracy_m": accuracy_m,
        "approximate_position": approximate,
        "message": message,
    }


@app.get("/route-to-exit")
def route_to_exit(
    start_floor: str = Query(..., description="Example: F6"),
    start: str = Query(..., description="Example: 641"),
    mode: str = Query(
        ...,
        description="lift or stairs",
        pattern="^(lift|stairs)$",
    ),
    blocked: Optional[List[str]] = Query(
        None,
        description=(
            "Optional blocked connector(s). "
            "Examples: blocked=LIFT3 or "
            "blocked=LIFT3&blocked=STAIRS2"
        ),
    ),
):
    con = get_connection()

    try:
        blocked_tokens = normalize_blocked(blocked)

        start_row = resolve_location_node(
            con,
            start_floor,
            start,
        )

        if not start_row:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Start location not found: "
                    f"{start_floor} / {start}"
                ),
            )

        path, cost, chosen_exit = best_exit_route(
            con,
            start_row["node_id"],
            mode,
            blocked_tokens=blocked_tokens,
        )

        if (
            path is None
            or chosen_exit is None
        ):
            raise HTTPException(
                status_code=404,
                detail=(
                    "No available exit route was found "
                    "with the selected travel mode and blocks."
                ),
            )

        response = build_route_response(
            con,
            path,
            cost,
            mode,
            start,
            "EXIT",
            blocked_tokens=blocked_tokens,
        )

        response["chosen_exit"] = {
            "node_id": chosen_exit["node_id"],
            "code": chosen_exit["original_node_id"],
            "label": friendly_entrance_label(
                chosen_exit["original_node_id"]
            ),
        }

        return response

    finally:
        con.close()


@app.get("/route")
def route(
    start_floor: str = Query(
        ...,
        description="Example: G",
    ),
    start: str = Query(
        ...,
        description="Example: ENTRANCE1-G or G41",
    ),
    destination_floor: str = Query(
        ...,
        description="Example: F7. Use G for EXIT.",
    ),
    destination: str = Query(
        ...,
        description="Example: 740 or EXIT",
    ),
    mode: str = Query(
        ...,
        description="lift or stairs",
        pattern="^(lift|stairs)$",
    ),
    blocked: Optional[List[str]] = Query(
        None,
        description=(
            "Optional blocked connector(s). "
            "Examples: blocked=LIFT3 or "
            "blocked=LIFT3&blocked=STAIRS2"
        ),
    ),
):
    con = get_connection()

    try:
        start_floor = start_floor.strip()
        start = start.strip()
        destination_floor = destination_floor.strip()
        destination = destination.strip()

        blocked_tokens = normalize_blocked(blocked)

        start_row = resolve_location_node(
            con,
            start_floor,
            start,
        )

        if not start_row:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Start location not found: "
                    f"{start_floor} / {start}"
                ),
            )

        # Special destination: EXIT / LEAVE BUILDING.
        if destination.upper() in EXIT_ALIASES:
            path, cost, chosen_exit = best_exit_route(
                con,
                start_row["node_id"],
                mode,
                blocked_tokens=blocked_tokens,
            )

            if (
                path is None
                or chosen_exit is None
            ):
                raise HTTPException(
                    status_code=404,
                    detail=(
                        "No available exit route was found "
                        "with the selected travel mode and blocks."
                    ),
                )

            response = build_route_response(
                con,
                path,
                cost,
                mode,
                start,
                "EXIT",
                blocked_tokens=blocked_tokens,
            )

            response["chosen_exit"] = {
                "node_id": chosen_exit["node_id"],
                "code": chosen_exit["original_node_id"],
                "label": friendly_entrance_label(
                    chosen_exit["original_node_id"]
                ),
            }

            return response

        destination_row = resolve_location_node(
            con,
            destination_floor,
            destination,
        )

        if not destination_row:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Destination not found: "
                    f"{destination_floor} / {destination}"
                ),
            )

        same_floor = (
            str(start_row["floor_id"]).upper()
            == str(destination_row["floor_id"]).upper()
        )

        path, cost = shortest_path(
            con,
            start_row["node_id"],
            destination_row["node_id"],
            mode,
            blocked_tokens=blocked_tokens,
            allow_vertical=not same_floor,
        )

        if path is None:
            if blocked_tokens:
                detail = (
                    "No route found with the selected travel mode "
                    "after applying the blocked connector(s): "
                    + ", ".join(sorted(blocked_tokens))
                )
            else:
                detail = "No route found."

            raise HTTPException(
                status_code=404,
                detail=detail,
            )

        return build_route_response(
            con,
            path,
            cost,
            mode,
            start,
            destination,
            blocked_tokens=blocked_tokens,
        )

    finally:
        con.close()
