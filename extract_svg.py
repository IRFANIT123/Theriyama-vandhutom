#!/usr/bin/env python3
"""
PRP E Block - SVG Navigation Data Extractor
============================================

Purpose
-------
Extract navigation data created in Inkscape from a floor-plan SVG.

Expected Inkscape layer names
-----------------------------
MAP - Walls
MAP - Rooms
MAP - Infrastructure
NAV - Nodes
NAV - Edges

The extractor intentionally does NOT try to interpret the architectural drawing.
It uses only the objects that were deliberately created for navigation.

Outputs
-------
nodes.csv
edges.csv
locations.csv
extraction_report.txt

Optionally also creates:
prp_navigation.db

Dependencies
------------
Python 3.10+ only. No external packages are required.

Example
-------
python extract_svg.py "E Block - Ground Floor.svg" --floor G --output ground_floor

For another floor:
python extract_svg.py "E Block - 1st Floor.svg" --floor F1 --output first_floor
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"
SVG_NS = "http://www.w3.org/2000/svg"
XML_NS = "http://www.w3.org/XML/1998/namespace"

INK_LABEL = f"{{{INKSCAPE_NS}}}label"

# Your PRP drawings are A3 at 1:100 and the SVG conversion used by Inkscape
# gives approximately 0.264583333 mm of paper per SVG unit.
# At 1:100, that is 0.0264583333 m in the real building per SVG unit.
DEFAULT_METERS_PER_SVG_UNIT = 0.0264583333333333

DEFAULT_SNAP_TOLERANCE = 5.0

# Rooms deliberately excluded from navigation on Ground Floor.
# They remain visible in MAP - Rooms but are not searchable destinations.
GROUND_FLOOR_EXCLUDED = {"G36", "G38", "G40", "G42"}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass
class Node:
    node_id: str
    node_type: str
    x: float
    y: float
    location_id: str | None = None
    source_svg_id: str | None = None


@dataclass(frozen=True)
class Edge:
    edge_id: str
    from_node: str
    to_node: str
    distance_m: float
    edge_type: str
    accessible: int = 1
    bidirectional: int = 1


# ---------------------------------------------------------------------------
# General XML helpers
# ---------------------------------------------------------------------------

def local_name(tag: str) -> str:
    """Return SVG tag name without XML namespace."""
    return tag.rsplit("}", 1)[-1]


def get_layer(root: ET.Element, label: str) -> ET.Element | None:
    """Find an Inkscape layer by its visible label."""
    for elem in root.iter():
        if local_name(elem.tag) != "g":
            continue
        if elem.get(INK_LABEL) == label:
            return elem
    return None


def parse_float(value: str | None, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def element_text(elem: ET.Element) -> str:
    return clean_text("".join(elem.itertext()))


# ---------------------------------------------------------------------------
# SVG transform handling
# ---------------------------------------------------------------------------

# Supports the transform forms normally produced by Inkscape:
# matrix(a,b,c,d,e,f)
# translate(x[,y])
# scale(x[,y])
# rotate(angle[,cx,cy])
# skewX(angle)
# skewY(angle)

Matrix = tuple[float, float, float, float, float, float]


def matrix_multiply(m1: Matrix, m2: Matrix) -> Matrix:
    a, b, c, d, e, f = m1
    g, h, i, j, k, l = m2
    return (
        a * g + c * h,
        b * g + d * h,
        a * i + c * j,
        b * i + d * j,
        a * k + c * l + e,
        b * k + d * l + f,
    )


def apply_matrix(m: Matrix, p: Point) -> Point:
    a, b, c, d, e, f = m
    return Point(a * p.x + c * p.y + e, b * p.x + d * p.y + f)


def identity_matrix() -> Matrix:
    return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def parse_transform(transform: str | None) -> Matrix:
    if not transform:
        return identity_matrix()

    result = identity_matrix()

    pattern = re.compile(r"([A-Za-z]+)\s*\(([^)]*)\)")
    for name, raw_args in pattern.findall(transform):
        nums = [
            float(x)
            for x in re.findall(
                r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?",
                raw_args,
            )
        ]

        name_lower = name.lower()

        if name_lower == "matrix":
            if len(nums) != 6:
                raise ValueError(f"Invalid matrix transform: {transform}")
            m = tuple(nums)  # type: ignore[assignment]

        elif name_lower == "translate":
            if len(nums) not in (1, 2):
                raise ValueError(f"Invalid translate transform: {transform}")
            tx = nums[0]
            ty = nums[1] if len(nums) == 2 else 0.0
            m = (1.0, 0.0, 0.0, 1.0, tx, ty)

        elif name_lower == "scale":
            if len(nums) not in (1, 2):
                raise ValueError(f"Invalid scale transform: {transform}")
            sx = nums[0]
            sy = nums[1] if len(nums) == 2 else sx
            m = (sx, 0.0, 0.0, sy, 0.0, 0.0)

        elif name_lower == "rotate":
            if len(nums) not in (1, 3):
                raise ValueError(f"Invalid rotate transform: {transform}")
            angle = math.radians(nums[0])
            cos_a = math.cos(angle)
            sin_a = math.sin(angle)
            rotation = (cos_a, sin_a, -sin_a, cos_a, 0.0, 0.0)

            if len(nums) == 3:
                cx, cy = nums[1], nums[2]
                to_origin = (1.0, 0.0, 0.0, 1.0, -cx, -cy)
                back = (1.0, 0.0, 0.0, 1.0, cx, cy)
                m = matrix_multiply(
                    matrix_multiply(back, rotation), to_origin
                )
            else:
                m = rotation

        elif name_lower == "skewx":
            angle = math.radians(nums[0])
            m = (1.0, 0.0, math.tan(angle), 1.0, 0.0, 0.0)

        elif name_lower == "skewy":
            angle = math.radians(nums[0])
            m = (1.0, math.tan(angle), 0.0, 1.0, 0.0, 0.0)

        else:
            raise ValueError(f"Unsupported SVG transform '{name}'")

        # SVG transform lists are applied in sequence.
        result = matrix_multiply(result, m)

    return result


def combined_transform(elem: ET.Element, parent_transforms: list[Matrix]) -> Matrix:
    m = identity_matrix()
    for parent in parent_transforms:
        m = matrix_multiply(m, parent)
    own = parse_transform(elem.get("transform"))
    return matrix_multiply(m, own)


# ---------------------------------------------------------------------------
# Node extraction
# ---------------------------------------------------------------------------

def classify_node(node_id: str, label: str | None) -> tuple[str, str | None]:
    """
    Return (node_type, location_id).

    Explicit node IDs/labels created in Inkscape take priority.
    Unnamed ellipse nodes become corridor nodes.
    """

    raw = (label or node_id or "").strip()
    upper = raw.upper()

    # Room IDs: G28, G29, 131, 143-A, etc.
    if re.fullmatch(r"(?:G\d{2,3}(?:-[12])?)", upper):
        # A room node such as G37-1 belongs to room G37.
        base = re.sub(r"-[12]$", "", upper)
        return "room", base

    if upper.startswith("LIFT"):
        return "lift", None

    if upper.startswith("STAIR"):
        return "stair", None

    if upper.startswith("ENTRANCE"):
        return "entrance", None

    # All other deliberately drawn navigation circles are corridor/junction.
    return "corridor", None


def extract_nodes(root: ET.Element) -> list[Node]:
    layer = get_layer(root, "NAV - Nodes")
    if layer is None:
        raise RuntimeError("Layer 'NAV - Nodes' was not found.")

    nodes: list[Node] = []
    seen_ids: set[str] = set()

    def walk(elem: ET.Element, inherited: list[Matrix]) -> None:
        current_transform = combined_transform(elem, inherited)

        if local_name(elem.tag) == "ellipse":
            node_id = (elem.get("id") or "").strip()
            if not node_id:
                raise RuntimeError("A navigation ellipse has no SVG id.")

            if node_id in seen_ids:
                raise RuntimeError(f"Duplicate navigation node id: {node_id}")
            seen_ids.add(node_id)

            cx = parse_float(elem.get("cx"))
            cy = parse_float(elem.get("cy"))
            p = apply_matrix(current_transform, Point(cx, cy))

            label = elem.get(INK_LABEL)
            node_type, location_id = classify_node(node_id, label)

            nodes.append(
                Node(
                    node_id=node_id,
                    node_type=node_type,
                    x=p.x,
                    y=p.y,
                    location_id=location_id,
                    source_svg_id=node_id,
                )
            )

        for child in list(elem):
            walk(child, inherited + [parse_transform(elem.get("transform"))])

    # Start children directly so layer transform is included exactly once.
    layer_transform = parse_transform(layer.get("transform"))
    for child in list(layer):
        walk(child, [layer_transform])

    return nodes


# ---------------------------------------------------------------------------
# SVG path parser
# ---------------------------------------------------------------------------

NUMBER_RE = re.compile(
    r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
)

TOKEN_RE = re.compile(
    r"[AaCcHhLlMmQqSsTtVvZz]|"
    r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
)


def tokenize_path(d: str) -> list[str]:
    return TOKEN_RE.findall(d or "")


def is_command(token: str) -> bool:
    return len(token) == 1 and token.isalpha()


def required_numbers(command: str) -> int:
    return {
        "M": 2, "L": 2, "H": 1, "V": 1,
        "C": 6, "S": 4, "Q": 4, "T": 2,
        "A": 7, "Z": 0,
    }[command.upper()]


def parse_path_endpoints(d: str) -> list[Point]:
    """
    Parse an SVG path and return the points at which each drawing command
    finishes.

    For routing, we need topology points, not every pixel along a line.
    Curves/arcs contribute their command endpoints.
    """

    tokens = tokenize_path(d)
    if not tokens:
        return []

    i = 0
    command: str | None = None
    current = Point(0.0, 0.0)
    subpath_start = current
    output: list[Point] = []

    # Used for smooth curves. We only need the endpoint, but maintaining
    # these makes parsing standards-compliant.
    previous_cubic_control: Point | None = None
    previous_quad_control: Point | None = None
    previous_command = ""

    while i < len(tokens):
        if is_command(tokens[i]):
            command = tokens[i]
            i += 1
            if command.upper() == "Z":
                current = subpath_start
                output.append(current)
                previous_cubic_control = None
                previous_quad_control = None
                previous_command = command
                command = None
                continue

        if command is None:
            raise ValueError("SVG path contains numbers without a command.")

        upper = command.upper()
        rel = command.islower()
        n = required_numbers(command)

        if n == 0:
            continue

        # A command can repeat without repeating its letter.
        if i + n > len(tokens):
            raise ValueError(f"Incomplete SVG path command '{command}'.")

        # Stop if the next token is another command.
        if any(is_command(t) for t in tokens[i:i+n]):
            raise ValueError(f"Incomplete SVG path command '{command}'.")

        vals = [float(x) for x in tokens[i:i+n]]
        i += n

        if upper == "M":
            x, y = vals
            if rel:
                p = Point(current.x + x, current.y + y)
            else:
                p = Point(x, y)
            current = p
            subpath_start = p
            output.append(current)

            # Subsequent coordinate pairs after M are implicit L commands.
            command = "l" if rel else "L"
            previous_cubic_control = None
            previous_quad_control = None
            previous_command = "M"
            continue

        if upper == "L":
            x, y = vals
            current = (
                Point(current.x + x, current.y + y)
                if rel else Point(x, y)
            )
            output.append(current)

        elif upper == "H":
            x = vals[0]
            current = (
                Point(current.x + x, current.y)
                if rel else Point(x, current.y)
            )
            output.append(current)

        elif upper == "V":
            y = vals[0]
            current = (
                Point(current.x, current.y + y)
                if rel else Point(current.x, y)
            )
            output.append(current)

        elif upper == "C":
            x1, y1, x2, y2, x, y = vals
            if rel:
                p2 = Point(current.x + x2, current.y + y2)
                end = Point(current.x + x, current.y + y)
            else:
                p2 = Point(x2, y2)
                end = Point(x, y)
            current = end
            previous_cubic_control = p2
            previous_quad_control = None
            output.append(current)

        elif upper == "S":
            x2, y2, x, y = vals
            if rel:
                end = Point(current.x + x, current.y + y)
                p2 = Point(current.x + x2, current.y + y2)
            else:
                end = Point(x, y)
                p2 = Point(x2, y2)
            current = end
            previous_cubic_control = p2
            previous_quad_control = None
            output.append(current)

        elif upper == "Q":
            x1, y1, x, y = vals
            if rel:
                control = Point(current.x + x1, current.y + y1)
                end = Point(current.x + x, current.y + y)
            else:
                control = Point(x1, y1)
                end = Point(x, y)
            current = end
            previous_quad_control = control
            previous_cubic_control = None
            output.append(current)

        elif upper == "T":
            x, y = vals
            end = (
                Point(current.x + x, current.y + y)
                if rel else Point(x, y)
            )
            current = end
            previous_quad_control = None
            previous_cubic_control = None
            output.append(current)

        elif upper == "A":
            # rx ry x-axis-rotation large-arc-flag sweep-flag x y
            x = vals[5]
            y = vals[6]
            current = (
                Point(current.x + x, current.y + y)
                if rel else Point(x, y)
            )
            previous_cubic_control = None
            previous_quad_control = None
            output.append(current)

        else:
            raise ValueError(f"Unsupported SVG path command '{command}'.")

        previous_command = command

    return output


# ---------------------------------------------------------------------------
# Edge extraction
# ---------------------------------------------------------------------------

def distance(a: Point, b: Point) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def nearest_node(point: Point, nodes: list[Node], tolerance: float) -> tuple[Node | None, float]:
    best_node: Node | None = None
    best_distance = float("inf")

    for node in nodes:
        d = distance(point, Point(node.x, node.y))
        if d < best_distance:
            best_distance = d
            best_node = node

    if best_node is None or best_distance > tolerance:
        return None, best_distance

    return best_node, best_distance


def infer_edge_type(a: Node, b: Node) -> str:
    types = {a.node_type, b.node_type}

    if "stair" in types:
        return "stair"
    if "lift" in types:
        return "lift"
    if "entrance" in types:
        return "entrance_access"
    if "room" in types:
        return "room_access"
    return "corridor"


def edge_is_accessible(a: Node, b: Node) -> int:
    """
    'accessible' here means usable by the navigation graph.

    Stairs are marked 0 because they are not universally wheelchair
    accessible. Lift connections remain 1.

    This is NOT a claim about the building's official accessibility status.
    """
    if a.node_type == "stair" or b.node_type == "stair":
        return 0
    return 1


def canonical_pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))


def extract_edges(
    root: ET.Element,
    nodes: list[Node],
    snap_tolerance: float,
) -> tuple[list[Edge], list[str], list[str]]:
    layer = get_layer(root, "NAV - Edges")
    if layer is None:
        raise RuntimeError("Layer 'NAV - Edges' was not found.")

    node_by_id = {n.node_id: n for n in nodes}
    unique_edges: dict[tuple[str, str], Edge] = {}
    warnings: list[str] = []
    path_records: list[str] = []

    def walk(elem: ET.Element, inherited: list[Matrix]) -> None:
        current_transform = combined_transform(elem, inherited)

        if local_name(elem.tag) == "path":
            path_id = elem.get("id", "<unnamed-path>")
            d = elem.get("d", "")

            if not d.strip():
                warnings.append(f"{path_id}: empty path data")
            else:
                try:
                    points = parse_path_endpoints(d)
                    transformed = [apply_matrix(current_transform, p) for p in points]

                    snapped: list[tuple[Node, float]] = []
                    for p in transformed:
                        node, error = nearest_node(p, nodes, snap_tolerance)
                        if node is None:
                            warnings.append(
                                f"{path_id}: point ({p.x:.3f}, {p.y:.3f}) "
                                f"did not snap to a node; nearest error={error:.3f}"
                            )
                            continue
                        snapped.append((node, error))

                    # Remove consecutive duplicate node matches.
                    clean: list[tuple[Node, float]] = []
                    for item in snapped:
                        if not clean or item[0].node_id != clean[-1][0].node_id:
                            clean.append(item)

                    if len(clean) < 2:
                        warnings.append(
                            f"{path_id}: fewer than 2 usable snapped nodes."
                        )
                    else:
                        path_records.append(
                            f"{path_id}: "
                            + " -> ".join(n.node_id for n, _ in clean)
                        )

                        for (na, _), (nb, _) in zip(clean, clean[1:]):
                            if na.node_id == nb.node_id:
                                continue

                            pair = canonical_pair(na.node_id, nb.node_id)
                            svg_distance = distance(
                                Point(na.x, na.y),
                                Point(nb.x, nb.y),
                            )
                            real_distance = (
                                svg_distance * DEFAULT_METERS_PER_SVG_UNIT
                            )

                            candidate = Edge(
                                edge_id="",
                                from_node=na.node_id,
                                to_node=nb.node_id,
                                distance_m=real_distance,
                                edge_type=infer_edge_type(na, nb),
                                accessible=edge_is_accessible(na, nb),
                                bidirectional=1,
                            )

                            # Keep the first edge if the same pair occurs
                            # multiple times. Duplicate paths do not create
                            # duplicate graph edges.
                            if pair not in unique_edges:
                                unique_edges[pair] = candidate

                except Exception as exc:
                    warnings.append(f"{path_id}: parsing error: {exc}")

        for child in list(elem):
            walk(child, inherited + [parse_transform(elem.get("transform"))])

    layer_transform = parse_transform(layer.get("transform"))
    for child in list(layer):
        walk(child, [layer_transform])

    edges: list[Edge] = []
    for index, e in enumerate(unique_edges.values(), start=1):
        edges.append(
            Edge(
                edge_id=f"E{index:04d}",
                from_node=e.from_node,
                to_node=e.to_node,
                distance_m=e.distance_m,
                edge_type=e.edge_type,
                accessible=e.accessible,
                bidirectional=e.bidirectional,
            )
        )

    return edges, warnings, path_records


# ---------------------------------------------------------------------------
# Room/location extraction
# ---------------------------------------------------------------------------

ROOM_RE = re.compile(r"^G\d{2,3}(?:-[A-Z0-9]+)?$|^\d{3}(?:-[A-Z0-9]+)?$")


def normalize_room_code(text: str) -> str:
    text = clean_text(text).upper()
    text = text.replace(" ", "-")
    # Normalize Ground Floor labels such as G-28 -> G28.
    text = re.sub(r"^G-(?=\d)", "G", text)
    return text


def room_type(code: str) -> str:
    """
    Only uses information explicitly established for the current Ground
    Floor data. Unknown rooms are kept as 'room' rather than guessed.
    """
    if code in {"G28", "G29"}:
        return "toilet" if code == "G28" else "room"
    return "room"


def extract_locations(
    root: ET.Element,
    floor_id: str,
    nodes: list[Node],
) -> list[dict[str, str | int | None]]:
    layer = get_layer(root, "MAP - Rooms")
    if layer is None:
        raise RuntimeError("Layer 'MAP - Rooms' was not found.")

    # Room nodes tell us which room labels are actually navigable.
    room_node_codes = {
        n.location_id
        for n in nodes
        if n.node_type == "room" and n.location_id
    }

    locations: list[dict[str, str | int | None]] = []
    seen: set[str] = set()

    for elem in layer.iter():
        if local_name(elem.tag) != "text":
            continue

        text = normalize_room_code(element_text(elem))
        if not text or not ROOM_RE.fullmatch(text):
            continue

        if text in seen:
            raise RuntimeError(f"Duplicate room label in MAP - Rooms: {text}")
        seen.add(text)

        excluded = text in GROUND_FLOOR_EXCLUDED if floor_id == "G" else False
        searchable = 0 if excluded else 1
        public_access = 0 if excluded else 1

        # A room must have a navigation node to be routable.
        if searchable and text not in room_node_codes:
            searchable = 0
            public_access = 0

        locations.append(
            {
                "location_id": text,
                "floor_id": floor_id,
                "code": text,
                "name": text,
                "type": room_type(text),
                "searchable": searchable,
                "public_access": public_access,
                "description": (
                    "Electrical/service room; excluded from navigation."
                    if excluded
                    else (
                        "No navigation node found in NAV - Nodes."
                        if text not in room_node_codes
                        else ""
                    )
                ),
            }
        )

    return locations


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def connected_components(nodes: list[Node], edges: list[Edge]) -> list[set[str]]:
    graph: dict[str, set[str]] = {n.node_id: set() for n in nodes}

    for e in edges:
        if e.from_node in graph and e.to_node in graph:
            graph[e.from_node].add(e.to_node)
            graph[e.to_node].add(e.from_node)

    remaining = set(graph)
    components: list[set[str]] = []

    while remaining:
        start = next(iter(remaining))
        stack = [start]
        comp: set[str] = set()

        while stack:
            cur = stack.pop()
            if cur in comp:
                continue
            comp.add(cur)
            remaining.discard(cur)
            stack.extend(graph[cur] - comp)

        components.append(comp)

    return components


def validate(
    floor_id: str,
    nodes: list[Node],
    edges: list[Edge],
    locations: list[dict[str, str | int | None]],
) -> list[str]:
    errors: list[str] = []

    node_ids = [n.node_id for n in nodes]
    if len(node_ids) != len(set(node_ids)):
        errors.append("Duplicate node IDs exist.")

    node_set = set(node_ids)

    for e in edges:
        if e.from_node not in node_set:
            errors.append(f"{e.edge_id}: missing from_node {e.from_node}")
        if e.to_node not in node_set:
            errors.append(f"{e.edge_id}: missing to_node {e.to_node}")
        if e.from_node == e.to_node:
            errors.append(f"{e.edge_id}: self-loop detected.")
        if e.distance_m <= 0:
            errors.append(f"{e.edge_id}: non-positive distance.")

    location_ids = {
        str(x["location_id"]) for x in locations
    }

    for n in nodes:
        if n.location_id and n.location_id not in location_ids:
            errors.append(
                f"Node {n.node_id} refers to missing location {n.location_id}."
            )

    comps = connected_components(nodes, edges)
    if len(comps) > 1:
        sizes = sorted((len(c) for c in comps), reverse=True)
        errors.append(
            f"Navigation graph has {len(comps)} disconnected components: {sizes}"
        )

    # Ground Floor-specific checks.
    if floor_id == "G":
        required_rooms = {"G28", "G29"}
        present_room_locations = {
            str(x["location_id"])
            for x in locations
            if int(x["searchable"]) == 1
        }

        missing = required_rooms - present_room_locations
        if missing:
            errors.append(
                "Required Ground Floor searchable rooms missing: "
                + ", ".join(sorted(missing))
            )

        for excluded in GROUND_FLOOR_EXCLUDED:
            if excluded in location_ids:
                row = next(
                    x for x in locations if x["location_id"] == excluded
                )
                if int(row["searchable"]) != 0:
                    errors.append(
                        f"{excluded} should be excluded but is searchable."
                    )

            if any(n.location_id == excluded for n in nodes):
                errors.append(
                    f"{excluded} has a navigation node but should be excluded."
                )

    return errors


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------

def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(
    output_dir: Path,
    floor_id: str,
    nodes: list[Node],
    edges: list[Edge],
    locations: list[dict[str, str | int | None]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    write_csv(
        output_dir / "nodes.csv",
        [
            "node_id",
            "floor_id",
            "node_type",
            "x",
            "y",
            "location_id",
            "source_svg_id",
        ],
        [
            {
                "node_id": n.node_id,
                "floor_id": floor_id,
                "node_type": n.node_type,
                "x": f"{n.x:.6f}",
                "y": f"{n.y:.6f}",
                "location_id": n.location_id or "",
                "source_svg_id": n.source_svg_id or "",
            }
            for n in nodes
        ],
    )

    write_csv(
        output_dir / "edges.csv",
        [
            "edge_id",
            "floor_id",
            "from_node",
            "to_node",
            "distance_m",
            "edge_type",
            "accessible",
            "bidirectional",
        ],
        [
            {
                "edge_id": e.edge_id,
                "floor_id": floor_id,
                "from_node": e.from_node,
                "to_node": e.to_node,
                "distance_m": f"{e.distance_m:.4f}",
                "edge_type": e.edge_type,
                "accessible": e.accessible,
                "bidirectional": e.bidirectional,
            }
            for e in edges
        ],
    )

    write_csv(
        output_dir / "locations.csv",
        [
            "location_id",
            "floor_id",
            "code",
            "name",
            "type",
            "searchable",
            "public_access",
            "description",
        ],
        locations,
    )


# ---------------------------------------------------------------------------
# SQLite database
# ---------------------------------------------------------------------------

def create_database(
    db_path: Path,
    floor_id: str,
    svg_path: Path,
    nodes: list[Node],
    edges: list[Edge],
    locations: list[dict[str, str | int | None]],
    svg_width: str,
    svg_height: str,
    viewbox: str,
) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if db_path.exists():
        db_path.unlink()

    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()

        cur.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE floors (
                floor_id TEXT PRIMARY KEY,
                floor_number INTEGER NOT NULL,
                name TEXT NOT NULL,
                display_order INTEGER NOT NULL
            );

            CREATE TABLE locations (
                location_id TEXT PRIMARY KEY,
                floor_id TEXT NOT NULL,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                searchable INTEGER NOT NULL CHECK(searchable IN (0,1)),
                public_access INTEGER NOT NULL CHECK(public_access IN (0,1)),
                description TEXT DEFAULT '',
                FOREIGN KEY(floor_id) REFERENCES floors(floor_id)
            );

            CREATE TABLE nodes (
                node_id TEXT PRIMARY KEY,
                floor_id TEXT NOT NULL,
                node_type TEXT NOT NULL,
                x REAL NOT NULL,
                y REAL NOT NULL,
                location_id TEXT,
                source_svg_id TEXT,
                FOREIGN KEY(floor_id) REFERENCES floors(floor_id),
                FOREIGN KEY(location_id) REFERENCES locations(location_id)
            );

            CREATE TABLE edges (
                edge_id TEXT PRIMARY KEY,
                floor_id TEXT NOT NULL,
                from_node TEXT NOT NULL,
                to_node TEXT NOT NULL,
                distance_m REAL NOT NULL CHECK(distance_m > 0),
                edge_type TEXT NOT NULL,
                accessible INTEGER NOT NULL CHECK(accessible IN (0,1)),
                bidirectional INTEGER NOT NULL CHECK(bidirectional IN (0,1)),
                FOREIGN KEY(floor_id) REFERENCES floors(floor_id),
                FOREIGN KEY(from_node) REFERENCES nodes(node_id),
                FOREIGN KEY(to_node) REFERENCES nodes(node_id)
            );

            CREATE TABLE floor_maps (
                map_id INTEGER PRIMARY KEY AUTOINCREMENT,
                floor_id TEXT NOT NULL,
                map_file TEXT NOT NULL,
                width TEXT,
                height TEXT,
                viewbox TEXT,
                coordinate_unit TEXT NOT NULL,
                meters_per_svg_unit REAL NOT NULL,
                FOREIGN KEY(floor_id) REFERENCES floors(floor_id)
            );

            CREATE INDEX idx_locations_floor
                ON locations(floor_id);

            CREATE INDEX idx_locations_searchable
                ON locations(searchable);

            CREATE INDEX idx_nodes_floor
                ON nodes(floor_id);

            CREATE INDEX idx_nodes_location
                ON nodes(location_id);

            CREATE INDEX idx_edges_from
                ON edges(from_node);

            CREATE INDEX idx_edges_to
                ON edges(to_node);
            """
        )

        floor_number = 0 if floor_id == "G" else int(
            re.sub(r"\D", "", floor_id) or "0"
        )

        cur.execute(
            """
            INSERT INTO floors
                (floor_id, floor_number, name, display_order)
            VALUES (?, ?, ?, ?)
            """,
            (
                floor_id,
                floor_number,
                "Ground Floor" if floor_id == "G" else floor_id,
                floor_number,
            ),
        )

        cur.executemany(
            """
            INSERT INTO locations
                (location_id, floor_id, code, name, type,
                 searchable, public_access, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    x["location_id"],
                    x["floor_id"],
                    x["code"],
                    x["name"],
                    x["type"],
                    x["searchable"],
                    x["public_access"],
                    x["description"],
                )
                for x in locations
            ],
        )

        cur.executemany(
            """
            INSERT INTO nodes
                (node_id, floor_id, node_type, x, y,
                 location_id, source_svg_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    n.node_id,
                    floor_id,
                    n.node_type,
                    n.x,
                    n.y,
                    n.location_id,
                    n.source_svg_id,
                )
                for n in nodes
            ],
        )

        cur.executemany(
            """
            INSERT INTO edges
                (edge_id, floor_id, from_node, to_node, distance_m,
                 edge_type, accessible, bidirectional)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    e.edge_id,
                    floor_id,
                    e.from_node,
                    e.to_node,
                    e.distance_m,
                    e.edge_type,
                    e.accessible,
                    e.bidirectional,
                )
                for e in edges
            ],
        )

        cur.execute(
            """
            INSERT INTO floor_maps
                (floor_id, map_file, width, height, viewbox,
                 coordinate_unit, meters_per_svg_unit)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                floor_id,
                svg_path.name,
                svg_width,
                svg_height,
                viewbox,
                "SVG user units",
                DEFAULT_METERS_PER_SVG_UNIT,
            ),
        )

        con.commit()

    finally:
        con.close()


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def write_report(
    path: Path,
    svg_path: Path,
    floor_id: str,
    nodes: list[Node],
    edges: list[Edge],
    locations: list[dict[str, str | int | None]],
    warnings: list[str],
    path_records: list[str],
    validation_errors: list[str],
) -> None:
    counts: dict[str, int] = {}
    for n in nodes:
        counts[n.node_type] = counts.get(n.node_type, 0) + 1

    components = connected_components(nodes, edges)

    lines = [
        "PRP E BLOCK SVG NAVIGATION EXTRACTION REPORT",
        "=" * 52,
        f"SVG file: {svg_path}",
        f"Floor: {floor_id}",
        "",
        "COUNTS",
        "-" * 20,
        f"Total nodes: {len(nodes)}",
        f"  Room nodes: {counts.get('room', 0)}",
        f"  Corridor nodes: {counts.get('corridor', 0)}",
        f"  Lift nodes: {counts.get('lift', 0)}",
        f"  Stair nodes: {counts.get('stair', 0)}",
        f"  Entrance nodes: {counts.get('entrance', 0)}",
        f"Unique graph edges: {len(edges)}",
        f"Room locations: {len(locations)}",
        f"Connected components: {len(components)}",
        "",
        "SEARCHABLE LOCATIONS",
        "-" * 20,
    ]

    for loc in locations:
        if int(loc["searchable"]) == 1:
            lines.append(
                f"{loc['location_id']} ({loc['type']})"
            )

    lines.extend(
        [
            "",
            "NON-SEARCHABLE LOCATIONS",
            "-" * 20,
        ]
    )

    for loc in locations:
        if int(loc["searchable"]) == 0:
            lines.append(
                f"{loc['location_id']}: {loc['description']}"
            )

    lines.extend(
        [
            "",
            "PATH TOPOLOGY EXTRACTED FROM NAV - Edges",
            "-" * 20,
        ]
    )
    lines.extend(path_records)

    lines.extend(
        [
            "",
            "WARNINGS",
            "-" * 20,
        ]
    )
    lines.extend(warnings or ["None"])

    lines.extend(
        [
            "",
            "VALIDATION",
            "-" * 20,
            "PASS" if not validation_errors else "FAIL",
        ]
    )
    if validation_errors:
        lines.extend(validation_errors)

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract PRP Inkscape SVG navigation data."
    )
    parser.add_argument(
        "svg",
        type=Path,
        help="Input SVG floor plan.",
    )
    parser.add_argument(
        "--floor",
        required=True,
        help="Floor ID, e.g. G, F1, F2, ... F7.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output directory. Defaults to <svg_stem>_extracted.",
    )
    parser.add_argument(
        "--snap-tolerance",
        type=float,
        default=DEFAULT_SNAP_TOLERANCE,
        help=(
            "Maximum SVG-unit distance for snapping edge points to "
            f"navigation nodes. Default: {DEFAULT_SNAP_TOLERANCE}"
        ),
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Do not create SQLite database.",
    )

    args = parser.parse_args()

    svg_path: Path = args.svg
    floor_id = args.floor.strip().upper()

    if not svg_path.exists():
        print(f"ERROR: SVG file not found: {svg_path}", file=sys.stderr)
        return 2

    if args.snap_tolerance <= 0:
        print("ERROR: snap tolerance must be > 0.", file=sys.stderr)
        return 2

    output_dir = args.output or svg_path.with_name(
        svg_path.stem + "_extracted"
    )

    try:
        print(f"Reading SVG: {svg_path}")
        tree = ET.parse(svg_path)
        root = tree.getroot()

        width = root.get("width", "")
        height = root.get("height", "")
        viewbox = root.get("viewBox", "")

        required_layers = [
            "MAP - Walls",
            "MAP - Rooms",
            "MAP - Infrastructure",
            "NAV - Nodes",
            "NAV - Edges",
        ]

        missing_layers = [
            x for x in required_layers
            if get_layer(root, x) is None
        ]

        if missing_layers:
            raise RuntimeError(
                "Required Inkscape layers are missing: "
                + ", ".join(missing_layers)
            )

        print("Extracting navigation nodes...")
        nodes = extract_nodes(root)
        print(f"  Nodes: {len(nodes)}")

        print("Extracting navigation edges...")
        edges, warnings, path_records = extract_edges(
            root,
            nodes,
            args.snap_tolerance,
        )
        print(f"  Unique edges: {len(edges)}")

        print("Extracting room/location labels...")
        locations = extract_locations(
            root,
            floor_id,
            nodes,
        )
        print(f"  Locations: {len(locations)}")

        print("Validating graph...")
        validation_errors = validate(
            floor_id,
            nodes,
            edges,
            locations,
        )

        write_outputs(
            output_dir,
            floor_id,
            nodes,
            edges,
            locations,
        )

        report_path = output_dir / "extraction_report.txt"
        write_report(
            report_path,
            svg_path,
            floor_id,
            nodes,
            edges,
            locations,
            warnings,
            path_records,
            validation_errors,
        )

        if not args.no_db:
            db_path = output_dir / "prp_navigation.db"
            create_database(
                db_path,
                floor_id,
                svg_path,
                nodes,
                edges,
                locations,
                width,
                height,
                viewbox,
            )
            print(f"  SQLite: {db_path}")

        print()
        print("=" * 52)
        print("EXTRACTION COMPLETE")
        print("=" * 52)
        print(f"Output directory : {output_dir}")
        print(f"Nodes            : {len(nodes)}")
        print(f"Edges            : {len(edges)}")
        print(f"Locations        : {len(locations)}")
        print(f"Warnings         : {len(warnings)}")
        print(f"Validation       : {'PASS' if not validation_errors else 'FAIL'}")

        if warnings:
            print()
            print("WARNING DETAILS:")
            for w in warnings[:20]:
                print(" -", w)
            if len(warnings) > 20:
                print(f" - ... and {len(warnings)-20} more")

        if validation_errors:
            print()
            print("VALIDATION ERRORS:")
            for e in validation_errors:
                print(" -", e)
            return 1

        return 0

    except ET.ParseError as exc:
        print(f"ERROR: SVG/XML parsing failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
