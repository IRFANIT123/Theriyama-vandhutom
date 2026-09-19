"""Capture representative routes from the running CampusNav API."""
import json
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

API = os.environ.get("CAMPUSNAV_API", "http://127.0.0.1:8000")
ROUTES = [
    ("G", "ENTRANCE1-G", "F2", "229", "stairs"),
    ("G", "G41", "F7", "740", "lift"),
    ("F7", "740", "G", "G41", "lift"),
    ("F6", "626", "F1", "131", "stairs"),
    ("F2", "229", "F5", "529", "lift"),
    ("F4", "429", "F7", "740", "stairs"),
    ("F2", "LIFT1-F2", "F5", "529", "lift"),
    ("G", "STAIRS1-G", "F2", "229", "stairs"),
    ("F2", "229", "F2", "235", "stairs"),
    ("G", "STAIRS1-G", "F2", "229", "stairs", ["STAIRS2"]),
    ("F2", "LIFT3-F2", "F5", "529", "lift", ["LIFT2"]),
]


def get(path):
    with urlopen(API + path, timeout=30) as response:
        return json.load(response)


def main():
    output = []
    assert get("/health")["floors"] == 8
    for floor in get("/floors"):
        with urlopen(API + "/map/" + floor["floor_id"], timeout=30) as response:
            assert b"<svg" in response.read()
    for spec in ROUTES:
        sf, start, df, destination, mode = spec[:5]
        params = dict(start_floor=sf, start=start, destination_floor=df,
                      destination=destination, mode=mode)
        if len(spec) > 5:
            params["blocked"] = spec[5]
        route = get("/route?" + urlencode(params, doseq=True))
        checkpoints = route["checkpoints"]
        assert checkpoints[0]["floor_id"] == sf
        assert checkpoints[-1]["floor_id"] == df
        assert checkpoints[-1]["progress_percent"] == 100
        assert checkpoints[-1]["remaining_distance_m"] == 0
        points = {p["node_id"]: (floor, p) for floor, rows in route["floor_routes"].items() for p in rows}
        for cp in checkpoints:
            floor, point = points[cp["node_id"]]
            assert floor == cp["floor_id"]
            assert point["x"] == cp["x"] and point["y"] == cp["y"]
            assert route["raw_node_path"][cp["path_index"]] == cp["node_id"]
        for index, (a, b) in enumerate(zip(checkpoints, checkpoints[1:])):
            assert a["path_index"] < b["path_index"]
            assert a["progress_percent"] <= b["progress_percent"]
            if a["floor_id"] != b["floor_id"]:
                assert b["path_index"] == a["path_index"] + 1
                expected = "LIFT" if mode == "lift" else "STAIRS"
                assert expected in a["node_id"] and expected in b["node_id"]
        output.append(dict(params=params, route=route))
        print(f"{mode}: {sf}/{start} -> {df}/{destination}; floors={' > '.join(route['floors'])}; "
              f"checkpoints={len(checkpoints)}; cost={route['total_cost']}")
        print("  " + " | ".join(f"{cp['checkpoint']}:{cp['floor_id']}/{cp['node_id']}" for cp in checkpoints))
    Path("verification").mkdir(exist_ok=True)
    Path("verification/routes.json").write_text(json.dumps(output, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
