"""
DEV-ONLY verification fixture.

Builds integration/building_navigation.db with the SAME schema backend/main.py
expects, using the NAV-Nodes / NAV-Edges / MAP-Rooms layers already embedded in
the real floor SVGs. This exists ONLY so the unmodified backend can be executed
locally for end-to-end frontend verification. It is not part of the app and the
real project database replaces it.
"""
import math
import os
import re
import sqlite3

from lxml import etree

SVG = "http://www.w3.org/2000/svg"
INK = "http://www.inkscape.org/namespaces/inkscape"

FLOORS = [
    ("G", 0, "Ground Floor", "f0"),
    ("F1", 1, "First Floor", "f1"),
    ("F2", 2, "Second Floor", "f2"),
    ("F3", 3, "Third Floor", "f3"),
    ("F4", 4, "Fourth Floor", "f4"),
    ("F5", 5, "Fifth Floor", "f5"),
    ("F6", 6, "Sixth Floor", "f6"),
    ("F7", 7, "Seventh Floor", "f7"),
]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "integration", "building_navigation.db")


def layer(root, name):
    for g in root.iter("{%s}g" % SVG):
        if (g.get("{%s}label" % INK) or "").strip().lower() == name.lower():
            return g
    return None


def abs_point(el, x, y):
    """Apply the element's own transform chain up to the SVG root."""
    node = el
    pt = (float(x), float(y))
    chain = []
    while node is not None and etree.QName(node).localname != "svg":
        t = node.get("transform")
        if t:
            chain.append(t)
        node = node.getparent()
    for t in chain:  # innermost first
        pt = apply_transform(t, pt)
    return pt


def apply_transform(t, pt):
    x, y = pt
    for fn, args in re.findall(r"(matrix|translate|scale)\(([^)]*)\)", t)[::-1]:
        v = [float(n) for n in re.split(r"[\s,]+", args.strip()) if n]
        if fn == "matrix" and len(v) == 6:
            a, b, c, d, e, f = v
            x, y = a * x + c * y + e, b * x + d * y + f
        elif fn == "translate":
            x, y = x + v[0], y + (v[1] if len(v) > 1 else 0)
        elif fn == "scale":
            sx = v[0]
            sy = v[1] if len(v) > 1 else sx
            x, y = x * sx, y * sy
    return (x, y)


def path_points(d):
    """Flatten an SVG path's line commands into absolute points."""
    tokens = re.findall(r"([MmLlHhVvZz])|(-?\d*\.?\d+(?:e-?\d+)?)", d)
    cmds, cur, out, start = [], None, [], None
    nums = []
    for letter, num in tokens:
        if letter:
            if cur:
                cmds.append((cur, nums))
            cur, nums = letter, []
        else:
            nums.append(float(num))
    if cur:
        cmds.append((cur, nums))

    px = py = 0.0
    for c, v in cmds:
        if c in "Mm":
            for i in range(0, len(v) - 1, 2):
                if c == "M":
                    px, py = v[i], v[i + 1]
                else:
                    px, py = px + v[i], py + v[i + 1]
                out.append((px, py))
                if start is None:
                    start = (px, py)
                c = "L" if c == "M" else "l"
        elif c in "Ll":
            for i in range(0, len(v) - 1, 2):
                px, py = (v[i], v[i + 1]) if c == "L" else (px + v[i], py + v[i + 1])
                out.append((px, py))
        elif c in "Hh":
            for n in v:
                px = n if c == "H" else px + n
                out.append((px, py))
        elif c in "Vv":
            for n in v:
                py = n if c == "V" else py + n
                out.append((px, py))
        elif c in "Zz" and out:
            out.append(out[0])
    return out


def connector_meta(name):
    n = name.upper().replace("-", " ")
    num = re.search(r"(\d+)", n)
    num = int(num.group(1)) if num else None
    if "LIFT" in n:
        return "lift", "lift", num
    if "STAIR" in n:
        return "stair", "stair", num
    if "ENTRANCE" in n:
        return "entrance", None, num
    return None, None, None


def main():
    nodes, edges, locations = [], [], []

    for floor_id, _num, _name, folder in FLOORS:
        svg_path = os.path.join(ROOT, folder, "map.svg")
        root = etree.parse(svg_path).getroot()

        nav = layer(root, "NAV - Nodes")
        raw = []
        used = {}
        if nav is not None:
            for el in nav.iter():
                ln = etree.QName(el).localname
                if ln not in ("ellipse", "circle"):
                    continue
                label = (el.get("{%s}label" % INK) or el.get("id") or "").strip()
                base = re.sub(r"-\d+$", "", label) or el.get("id")
                x, y = abs_point(el, el.get("cx", 0), el.get("cy", 0))
                raw.append({"label": base, "x": x, "y": y, "id": el.get("id")})

        for i, r in enumerate(raw):
            name = r["label"]
            ntype, ckind, cnum = connector_meta(name)
            if ntype is None:
                # Room-code node (G31) vs anonymous corridor vertex (ellipse10).
                if re.fullmatch(r"[A-Za-z]?\d{2,4}[A-Za-z]?", name or ""):
                    ntype, code = "room", name.upper()
                else:
                    ntype, code = "corridor", None
                original = code or f"{floor_id}-NAV{i:03d}"
            else:
                key = name.upper().replace(" ", "")
                used[key] = used.get(key, 0) + 1
                if ntype == "entrance":
                    original = f"ENTRANCE{cnum or 1}-{floor_id}"
                else:
                    original = f"{'LIFT' if ntype=='lift' else 'STAIRS'}{cnum or 1}-{floor_id}"
                code = original
            r["node_id"] = f"{floor_id}-N{i:03d}"
            r["original"] = original
            r["ntype"] = ntype
            r["ckind"] = ckind
            r["cnum"] = cnum
            r["code"] = code if ntype in ("room",) else None

        by_pos = raw

        def nearest(pt, tol=26.0):
            best, bd = None, tol
            for r in by_pos:
                d = math.hypot(r["x"] - pt[0], r["y"] - pt[1])
                if d < bd:
                    best, bd = r, d
            return best

        nav_edges = layer(root, "NAV - Edges")
        seen = set()
        if nav_edges is not None:
            for el in nav_edges.iter():
                ln = etree.QName(el).localname
                pts = []
                if ln == "path" and el.get("d"):
                    pts = [abs_point(el, x, y) for x, y in path_points(el.get("d"))]
                elif ln == "line":
                    pts = [
                        abs_point(el, el.get("x1", 0), el.get("y1", 0)),
                        abs_point(el, el.get("x2", 0), el.get("y2", 0)),
                    ]
                elif ln in ("polyline", "polygon"):
                    nums = [float(n) for n in re.split(r"[\s,]+", (el.get("points") or "").strip()) if n]
                    pts = [abs_point(el, nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]
                for a, b in zip(pts, pts[1:]):
                    na, nb = nearest(a), nearest(b)
                    if not na or not nb or na["node_id"] == nb["node_id"]:
                        continue
                    key = tuple(sorted((na["node_id"], nb["node_id"])))
                    if key in seen:
                        continue
                    seen.add(key)
                    dist = math.hypot(na["x"] - nb["x"], na["y"] - nb["y"]) * 0.25
                    edges.append((f"E{len(edges):05d}", key[0], key[1], round(dist, 2), "walk", 0, 1))

        # Ensure the floor graph is connected (SVG edge layers have small gaps).
        comp = {r["node_id"]: r["node_id"] for r in by_pos}

        def find(a):
            while comp[a] != a:
                comp[a] = comp[comp[a]]
                a = comp[a]
            return a

        for _e, a, b, *_ in edges:
            if a in comp and b in comp:
                comp[find(a)] = find(b)
        groups = {}
        for r in by_pos:
            groups.setdefault(find(r["node_id"]), []).append(r)
        gl = list(groups.values())
        while len(gl) > 1:
            base = gl[0]
            best = None
            for other in gl[1:]:
                for p in base:
                    for q in other:
                        d = math.hypot(p["x"] - q["x"], p["y"] - q["y"])
                        if best is None or d < best[0]:
                            best = (d, p, q, other)
            d, p, q, other = best
            edges.append((f"E{len(edges):05d}", p["node_id"], q["node_id"], round(d * 0.25, 2), "walk", 0, 1))
            gl = [base + other] + [g for g in gl[1:] if g is not other]

        for r in by_pos:
            loc_id = None
            if r["ntype"] == "room" and r["code"]:
                loc_id = f"L-{floor_id}-{r['code']}"
                locations.append((loc_id, floor_id, r["code"], f"Room {r['code']}", "classroom", 1))
            elif r["ntype"] in ("lift", "stair", "entrance"):
                loc_id = f"L-{r['original']}"
                pretty = {"lift": "Lift", "stair": "Staircase", "entrance": "Entrance"}[r["ntype"]]
                locations.append(
                    (loc_id, floor_id, r["original"], f"{pretty} {r['cnum'] or ''}".strip(), r["ntype"], 1)
                )
            nodes.append(
                (
                    r["node_id"], floor_id, r["original"], r["ntype"],
                    round(r["x"], 3), round(r["y"], 3), r["ckind"], r["cnum"], loc_id,
                )
            )

    # Vertical connector edges between consecutive floors.
    order = [f[0] for f in FLOORS]
    by_floor = {}
    for n in nodes:
        by_floor.setdefault(n[1], []).append(n)
    for a, b in zip(order, order[1:]):
        for na in by_floor.get(a, []):
            if na[3] not in ("lift", "stair"):
                continue
            for nb in by_floor.get(b, []):
                if nb[3] == na[3] and nb[7] == na[7]:
                    mode = "lift" if na[3] == "lift" else "stair"
                    cost = 12.0 if mode == "lift" else 22.0
                    edges.append((f"E{len(edges):05d}", na[0], nb[0], cost, mode, 1, 1))

    os.makedirs(os.path.dirname(DB), exist_ok=True)
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript(
        """
        CREATE TABLE floors(floor_id TEXT PRIMARY KEY, floor_number INTEGER, name TEXT);
        CREATE TABLE locations(location_id TEXT PRIMARY KEY, floor_id TEXT, code TEXT,
                               name TEXT, type TEXT, searchable INTEGER);
        CREATE TABLE nodes(node_id TEXT PRIMARY KEY, floor_id TEXT, original_node_id TEXT,
                           node_type TEXT, x REAL, y REAL, connector_kind TEXT,
                           connector_number INTEGER, location_id TEXT);
        CREATE TABLE edges(edge_id TEXT PRIMARY KEY, from_node TEXT, to_node TEXT,
                           distance_m REAL, travel_mode TEXT, is_vertical INTEGER,
                           bidirectional INTEGER, edge_type TEXT);
        CREATE TABLE floor_maps(floor_id TEXT PRIMARY KEY, meters_per_svg_unit REAL);
        """
    )
    con.executemany("INSERT INTO floors VALUES(?,?,?)", [(f[0], f[1], f[2]) for f in FLOORS])
    seen_loc = set()
    for loc in locations:
        if loc[0] in seen_loc:
            continue
        seen_loc.add(loc[0])
        con.execute("INSERT INTO locations VALUES(?,?,?,?,?,?)", loc)
    con.executemany("INSERT INTO nodes VALUES(?,?,?,?,?,?,?,?,?)", nodes)
    con.executemany("INSERT INTO edges VALUES(?,?,?,?,?,?,?,?)",
                    [e + ("vertical" if e[5] else "walk",) for e in edges])
    con.executemany("INSERT INTO floor_maps VALUES(?,?)", [(f[0], 0.25) for f in FLOORS])
    con.commit()
    print(f"nodes={len(nodes)} edges={len(edges)} locations={len(seen_loc)}")
    con.close()


if __name__ == "__main__":
    main()
