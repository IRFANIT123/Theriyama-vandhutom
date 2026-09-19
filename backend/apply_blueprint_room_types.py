"""Apply the room uses shown on the supplied E Block architectural plans.

The migration is deliberately explicit: every location row in the integrated
database must have a floor/code entry below. This prevents a later database
rebuild from silently turning verified bathrooms and teaching spaces back into
generic rooms.
"""

from __future__ import annotations

import math
import shutil
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "integration" / "building_navigation.db"
BACKUP = ROOT / "integration" / "building_navigation.db.before-blueprint-types-20260917.bak"


def records(codes: str, name: str, room_type: str) -> dict[str, tuple[str, str]]:
    return {code: (name, room_type) for code in codes.split()}


BLUEPRINT_ROOMS: dict[str, dict[str, tuple[str, str]]] = {
    "G": {
        **records("G28 G29 G30", "Bathroom", "bathroom"),
        **records("G31 G32 G33 G34", "Classroom", "classroom"),
        **records("G35 G36", "Staff Bathroom", "bathroom"),
        "G37": ("Faculty Room", "faculty_room"),
        "G38": ("Electrical Room", "electrical_room"),
        "G39": ("Free Room", "multipurpose_room"),
        "G40": ("Electrical Room", "electrical_room"),
        "G41": ("Faculty Room", "faculty_room"),
        "G42": ("Communication Room", "communication_room"),
    },
    "F1": {
        **records("131 132 133", "Bathroom", "bathroom"),
        **records("134 135 136 137 138", "Classroom", "classroom"),
        **records("139 140", "Staff Bathroom", "bathroom"),
        "141": ("Faculty Room", "faculty_room"),
        "142": ("Electrical Room", "electrical_room"),
        **records("143 143-A", "Faculty Room", "faculty_room"),
        "144": ("Electrical Room", "electrical_room"),
        "145": ("Faculty Room", "faculty_room"),
    },
    "F2": {
        **records("227 228", "Bathroom", "bathroom"),
        **records("229 230 231 232 233 234", "Classroom", "classroom"),
        **records("235 236", "Staff Bathroom", "bathroom"),
        "237": ("Electrical Room", "electrical_room"),
        **records("238 238-A", "Smart Classroom", "smart_classroom"),
        "239": ("Faculty Room", "faculty_room"),
        "240": ("Electrical Room", "electrical_room"),
    },
    "F3": {
        **records("326 327 328", "Bathroom", "bathroom"),
        **records("329 330", "Classroom", "classroom"),
        "331": ("Faculty Room", "faculty_room"),
        **records("332 333 334", "Classroom", "classroom"),
        **records("335 336", "Staff Bathroom", "bathroom"),
        "337": ("Faculty Room", "faculty_room"),
        "338": ("Electrical Room", "electrical_room"),
        "339": ("Classroom", "classroom"),
        "340": ("Electrical Room", "electrical_room"),
        "341": ("Faculty Room", "faculty_room"),
    },
    "F4": {
        **records("421 422 423", "Bathroom", "bathroom"),
        **records("424 425 426 427", "Classroom", "classroom"),
        "428": ("Faculty Room", "faculty_room"),
        "429": ("Classroom", "classroom"),
        **records("430 431", "Staff Bathroom", "bathroom"),
        "432": ("Faculty Room", "faculty_room"),
        "433": ("Electrical Room", "electrical_room"),
        "434": ("Classroom", "classroom"),
        "434-A": ("CCE Lab", "laboratory"),
        "435": ("Electrical Room", "electrical_room"),
        "436": ("Faculty Room", "faculty_room"),
    },
    "F5": {
        **records("526 527 528", "Bathroom", "bathroom"),
        **records("529 530 531 532", "Classroom", "classroom"),
        "533": ("Faculty Room", "faculty_room"),
        "534": ("Classroom", "classroom"),
        **records("535 536", "Staff Bathroom", "bathroom"),
        "537": ("Faculty Room", "faculty_room"),
        "538": ("Electrical Room", "electrical_room"),
        "539": ("Auditorium", "auditorium"),
        "540": ("Electrical Room", "electrical_room"),
        "541": ("Faculty Room", "faculty_room"),
    },
    "F6": {
        **records("626 627 628", "Bathroom", "bathroom"),
        **records("629 630", "Classroom", "classroom"),
        "631": ("Faculty Room", "faculty_room"),
        **records("632 633 634", "Classroom", "classroom"),
        **records("635 636", "Staff Bathroom", "bathroom"),
        "637": ("Faculty Room", "faculty_room"),
        "638": ("Electrical Room", "electrical_room"),
        "639": ("Classroom", "classroom"),
        "640": ("Electrical Room", "electrical_room"),
        "641": ("Faculty Room", "faculty_room"),
    },
    "F7": {
        **records("728 729 730", "Bathroom", "bathroom"),
        **records("731 732", "Classroom", "classroom"),
        "733": ("Faculty Room", "faculty_room"),
        **records("734 735 736", "Classroom", "classroom"),
        **records("737 738", "Staff Bathroom", "bathroom"),
        "739": ("Electrical Room", "electrical_room"),
        "740": ("Faculty Room", "faculty_room"),
        "741": ("Electrical Room", "electrical_room"),
    },
}


TYPE_DESCRIPTION = {
    "bathroom": "Blueprint-verified bathroom / toilet.",
    "classroom": "Blueprint-verified classroom.",
    "faculty_room": "Blueprint-verified faculty room.",
    "electrical_room": "Blueprint-verified electrical room.",
    "communication_room": "Blueprint-verified communication room.",
    "multipurpose_room": "Blueprint-verified free / flexible room.",
    "smart_classroom": "Blueprint-verified smart classroom.",
    "laboratory": "Blueprint-verified CCE laboratory.",
    "auditorium": "Blueprint-verified auditorium.",
}


def ensure_f5_room_538_navigation(connection: sqlite3.Connection) -> None:
    """Attach blueprint room 538 to its real south doorway and corridor.

    The electrical room remains non-public, but it is a valid searchable indoor
    destination. Its doorway is the opening at x=544.7..562.4 on the room's
    south wall. The corridor point lies directly on the existing ellipse34 to
    circle52 hallway segment, so no wall-crossing shortcut is introduced.
    """

    floor_id = "F5"
    room_node = (553.5, 653.5)
    doorway_node = (553.5, 683.6)
    scale_row = connection.execute(
        "SELECT meters_per_svg_unit FROM floor_maps WHERE floor_id = ?",
        (floor_id,),
    ).fetchone()
    scale = float(scale_row[0]) if scale_row and scale_row[0] else 0.0264583333333333

    connection.execute(
        """
        UPDATE locations
           SET searchable = 1,
               public_access = 0,
               description = ?
         WHERE floor_id = ? AND code = '538'
        """,
        (
            "Blueprint-verified electrical room. Routable to its marked south doorway; restricted room access may still apply.",
            floor_id,
        ),
    )

    nodes = (
        (
            "538", floor_id, "538", "room", room_node[0], room_node[1],
            "538", "room-538-route", None, None,
        ),
        (
            "F5_538_DOOR", floor_id, "F5-538-DOOR", "corridor",
            doorway_node[0], doorway_node[1], None, "room-538-door", None, None,
        ),
    )
    connection.executemany(
        """
        INSERT INTO nodes (
            node_id, floor_id, original_node_id, node_type, x, y,
            location_id, source_svg_id, connector_kind, connector_number
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(node_id) DO UPDATE SET
            floor_id = excluded.floor_id,
            original_node_id = excluded.original_node_id,
            node_type = excluded.node_type,
            x = excluded.x,
            y = excluded.y,
            location_id = excluded.location_id,
            source_svg_id = excluded.source_svg_id,
            connector_kind = excluded.connector_kind,
            connector_number = excluded.connector_number
        """,
        nodes,
    )

    corridor_targets = ["F5_ellipse34"]
    if connection.execute(
        "SELECT 1 FROM nodes WHERE node_id = 'circle52' AND floor_id = 'F5'"
    ).fetchone():
        corridor_targets.append("circle52")

    def distance_to(node_id: str) -> float:
        row = connection.execute(
            "SELECT x, y FROM nodes WHERE node_id = ?",
            (node_id,),
        ).fetchone()
        if not row:
            raise RuntimeError(f"Required Floor 5 corridor node is missing: {node_id}")
        return math.hypot(float(row[0]) - doorway_node[0], float(row[1]) - doorway_node[1]) * scale

    edges = [
        (
            "BLUEPRINT_F5_538_ROOM", "538", "F5_538_DOOR",
            math.dist(room_node, doorway_node) * scale, "room_access",
            "walk", 0, 1, 1, floor_id, floor_id, "BLUEPRINT_F5_538_ROOM",
        )
    ]
    for index, target in enumerate(corridor_targets, start=1):
        edge_id = f"BLUEPRINT_F5_538_CORRIDOR_{index}"
        edges.append(
            (
                edge_id, "F5_538_DOOR", target, distance_to(target), "corridor",
                "walk", 0, 1, 1, floor_id, floor_id, edge_id,
            )
        )
    connection.executemany(
        """
        INSERT INTO edges (
            edge_id, from_node, to_node, distance_m, edge_type, travel_mode,
            is_vertical, accessible, bidirectional, from_floor, to_floor, source_edge_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(edge_id) DO UPDATE SET
            from_node = excluded.from_node,
            to_node = excluded.to_node,
            distance_m = excluded.distance_m,
            edge_type = excluded.edge_type,
            travel_mode = excluded.travel_mode,
            is_vertical = excluded.is_vertical,
            accessible = excluded.accessible,
            bidirectional = excluded.bidirectional,
            from_floor = excluded.from_floor,
            to_floor = excluded.to_floor,
            source_edge_id = excluded.source_edge_id
        """,
        edges,
    )


def ensure_f5_route_wall_clearance(connection: sqlite3.Connection) -> None:
    """Move the sparse west corridor spine off the room-wall edge.

    The original ellipse48/ellipse49 coordinates sit only about one wall-width
    from the classroom fronts. In the projected view, joining those sparse
    points creates a chord that appears to cut through the 534/532 walls. The
    adjusted points stay on the same walkable corridor, centered between the
    room fronts (about x=295) and the open-space edge (about x=335).
    """

    positions = {
        "F5_ellipse48": (316.0, 552.0),
        "F5_ellipse49": (316.0, 718.0),
    }
    for node_id, (x, y) in positions.items():
        if not connection.execute(
            "SELECT 1 FROM nodes WHERE node_id = ? AND floor_id = 'F5'",
            (node_id,),
        ).fetchone():
            raise RuntimeError(f"Required Floor 5 route node is missing: {node_id}")
        connection.execute(
            "UPDATE nodes SET x = ?, y = ? WHERE node_id = ? AND floor_id = 'F5'",
            (x, y, node_id),
        )

    scale_row = connection.execute(
        "SELECT meters_per_svg_unit FROM floor_maps WHERE floor_id = 'F5'"
    ).fetchone()
    scale = float(scale_row[0]) if scale_row and scale_row[0] else 0.0264583333333333
    affected = connection.execute(
        """
        SELECT edge_id, from_node, to_node
          FROM edges
         WHERE is_vertical = 0
           AND (from_node IN ('F5_ellipse48', 'F5_ellipse49')
             OR to_node IN ('F5_ellipse48', 'F5_ellipse49'))
        """
    ).fetchall()
    for edge_id, from_node, to_node in affected:
        start = connection.execute(
            "SELECT x, y FROM nodes WHERE node_id = ?", (from_node,)
        ).fetchone()
        end = connection.execute(
            "SELECT x, y FROM nodes WHERE node_id = ?", (to_node,)
        ).fetchone()
        if not start or not end:
            raise RuntimeError(f"Cannot recalculate incomplete edge: {edge_id}")
        distance = math.hypot(float(end[0]) - float(start[0]), float(end[1]) - float(start[1])) * scale
        connection.execute(
            "UPDATE edges SET distance_m = ? WHERE edge_id = ?",
            (distance, edge_id),
        )


def ensure_stair3_upward_direction(connection: sqlite3.Connection) -> None:
    """Keep Stair 3's upward run right-to-left on every intermediate floor.

    Floor 1 was imported with its D/U endpoints opposite to Floors 2-7. Swap
    the Floor 1 endpoint coordinates and their horizontal attachments while
    leaving vertical D/U connections semantic. Physical edge lengths remain
    unchanged because every horizontal attachment stays at the same position.
    """

    down_id, up_id = "STAIRS3-F1-D", "STAIRS3-F1-U"
    rows = {
        row["node_id"]: row
        for row in connection.execute(
            "SELECT node_id, x, y FROM nodes WHERE node_id IN (?, ?)",
            (down_id, up_id),
        )
    }
    if set(rows) != {down_id, up_id}:
        raise RuntimeError("Floor 1 Stair 3 D/U endpoints are incomplete")

    down, up = rows[down_id], rows[up_id]
    if float(down["x"]) < float(up["x"]):
        connection.execute(
            "UPDATE nodes SET x = ?, y = ? WHERE node_id = ?",
            (float(up["x"]), float(up["y"]), down_id),
        )
        connection.execute(
            "UPDATE nodes SET x = ?, y = ? WHERE node_id = ?",
            (float(down["x"]), float(down["y"]), up_id),
        )
        connection.execute(
            """
            UPDATE edges
               SET from_node = CASE from_node
                     WHEN 'STAIRS3-F1-D' THEN 'STAIRS3-F1-U'
                     WHEN 'STAIRS3-F1-U' THEN 'STAIRS3-F1-D'
                     ELSE from_node END,
                   to_node = CASE to_node
                     WHEN 'STAIRS3-F1-D' THEN 'STAIRS3-F1-U'
                     WHEN 'STAIRS3-F1-U' THEN 'STAIRS3-F1-D'
                     ELSE to_node END
             WHERE is_vertical = 0
               AND (from_node IN ('STAIRS3-F1-D', 'STAIRS3-F1-U')
                 OR to_node IN ('STAIRS3-F1-D', 'STAIRS3-F1-U'))
            """
        )

    inconsistent = connection.execute(
        """
        SELECT d.floor_id, d.x AS down_x, u.x AS up_x
          FROM nodes d
          JOIN nodes u ON u.floor_id = d.floor_id
         WHERE d.node_id LIKE 'STAIRS3-%-D'
           AND u.node_id = REPLACE(d.node_id, '-D', '-U')
           AND d.floor_id IN ('F1','F2','F3','F4','F5','F6','F7')
           AND d.x <= u.x
        """
    ).fetchall()
    if inconsistent:
        raise RuntimeError(f"Inconsistent Stair 3 upward direction: {inconsistent}")


def main() -> None:
    if not DATABASE.exists():
        raise SystemExit(f"Database not found: {DATABASE}")
    if not BACKUP.exists():
        shutil.copy2(DATABASE, BACKUP)

    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    try:
        stored = {
            (row["floor_id"], row["code"]): row
            for row in connection.execute("SELECT * FROM locations")
        }
        expected = {
            (floor_id, code): metadata
            for floor_id, floor_records in BLUEPRINT_ROOMS.items()
            for code, metadata in floor_records.items()
        }
        missing_from_plan = sorted(set(stored) - set(expected))
        missing_from_database = sorted(set(expected) - set(stored))
        if missing_from_plan or missing_from_database:
            raise RuntimeError(
                "Blueprint mapping/database mismatch. "
                f"Unmapped rows={missing_from_plan}; missing rows={missing_from_database}"
            )

        connection.execute("BEGIN IMMEDIATE")
        for key, (name, room_type) in expected.items():
            floor_id, code = key
            previous = stored[key]
            access_note = (
                "No routable navigation node is stored for this location."
                if int(previous["searchable"]) == 0
                else ""
            )
            description = TYPE_DESCRIPTION[room_type]
            if access_note:
                description = f"{description} {access_note}"
            connection.execute(
                """
                UPDATE locations
                   SET name = ?, type = ?, description = ?
                 WHERE floor_id = ? AND code = ?
                """,
                (name, room_type, description, floor_id, code),
            )
        ensure_f5_room_538_navigation(connection)
        ensure_f5_route_wall_clearance(connection)
        ensure_stair3_upward_direction(connection)
        connection.commit()

        counts: dict[str, Counter[str]] = defaultdict(Counter)
        for row in connection.execute(
            "SELECT floor_id, type FROM locations ORDER BY floor_id, code"
        ):
            counts[row["floor_id"]][row["type"]] += 1
        total = sum(sum(values.values()) for values in counts.values())
        print(f"Updated {total} location records in {DATABASE}")
        print(f"Backup: {BACKUP}")
        for floor_id in ["G", "F1", "F2", "F3", "F4", "F5", "F6", "F7"]:
            summary = ", ".join(
                f"{room_type}={count}" for room_type, count in sorted(counts[floor_id].items())
            )
            print(f"{floor_id}: {summary}")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
