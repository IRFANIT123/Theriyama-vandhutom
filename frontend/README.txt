CampusNav Frontend
==================

WHAT THIS ZIP IS
----------------
A drop-in replacement for the frontend folder. It uses plain HTML/CSS/JavaScript and needs no npm/build step.

INSTALL
-------
1. Back up your current frontend folder.
2. Replace it with the frontend folder from this ZIP.
3. Keep your existing backend, integration/building_navigation.db, and f0..f7 SVG map folders unchanged.

RUN
---
Backend, from project root:
    python -m uvicorn backend.main:app --reload

Frontend, from project root:
    python -m http.server 5500 --directory frontend

Open:
    http://127.0.0.1:5500/

LOCAL VERIFICATION / PORT CONFLICTS (2026-09-16)
----------------------------------------------
Create a project-local environment if Python dependencies are not installed:
    python -m venv .venv
    .venv\Scripts\python.exe -m pip install -r backend\requirements.txt

When port 8000 is occupied, run from the project root:
    .venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8001 --reload --reload-dir backend
    .venv\Scripts\python.exe frontend\dev_server.py --port 3000 --backend http://127.0.0.1:8001

Open the frontend with its same-origin API proxy:
    http://127.0.0.1:3000/?api=/api

The original static-server setup still works. The optional ?api= parameter
overrides the default http://127.0.0.1:8000 API address. The development server
forwards /api/* to FastAPI; it does not alter routes or map coordinates.

PATCH — consistent hand-off on undo and connector-start reroutes
- Previous Point restores the arrival-floor view when the restored confirmed
  checkpoint is a departure connector; progress stays at that departure point.
- Routes beginning at a confirmed connector show the next floor immediately.
- app.js has a versioned URL so browser caches receive this update.
- Exact tested routes and results: ../verification/2026-09-16-hand-off.md

BACKEND API USED
----------------
GET /health
GET /floors
GET /maps
GET /map/{floor_id}
GET /locations?floor_id=...
GET /entrances
GET /nearest-entrance?latitude=...&longitude=...&accuracy_m=...
GET /route?...&blocked=...
GET /route-to-exit?...&blocked=...

IMPLEMENTED
-----------
- Responsive two-part navigation UI: one stateful route sidebar and one dominant map.
- Vertical floor rail on the map edge; active routes show only relevant floors.
- Semantic map palette: rooms cool neutral, corridors blue-grey, lifts purple, stairs amber, bathrooms teal.
- Bathroom icon added where bathroom/toilet room data can be matched to SVG room labels.
- Technical NAV node/edge layers are hidden.
- Permanent walkable-corridor visualization reconstructed conservatively from NAV edges only when safe source corridor geometry is unavailable.
- Room-door destination spurs are excluded from broad corridor painting.
- Active route is drawn only from backend floor_routes/raw path data.
- Route uses a high-contrast blue line + white halo and explicit directional arrowheads.
- Only micro-jitter that is nearly collinear is simplified; meaningful turns are retained.
- Up to backend-provided meaningful checkpoints are shown; raw A* nodes remain hidden.
- Manual indoor position: tap the next checkpoint when physically reached.
- Completed route/checkpoints disappear from the active view as progress advances.
- Previous Point undoes one progress step.
- Current Point recenters on the latest manually confirmed checkpoint.
- Automatic floor switching and centering on checkpoint progression.
- Searchable exit UX: nearest exit + each physical entrance as an exit.
- Outdoor browser GPS -> backend nearest entrance.
- Lift/stairs mode selector.
- Pre-route and mid-route blocked connector selection.
- Mid-route reroute starts from the latest confirmed checkpoint using its backend original node identifier.
- Frontend-only 90 degree clockwise map rotation via shared SVG transform/viewBox strategy.
- Pan, mouse-wheel zoom, zoom buttons and Fit Map.
- Turn directions derived only from actual backend route geometry plus authoritative backend floor-change/connector instructions.

IMPORTANT POSITION MODEL
------------------------
GPS is intentionally used only to identify the closest entrance outdoors.
Indoor position is user-confirmed by tapping route checkpoints. "Current Point" means the latest manually confirmed checkpoint, not indoor GPS.

MAP / ROUTE SAFETY
------------------
The frontend does not create a new navigation graph and does not alter backend route coordinates.
Route drawing follows backend floor_routes. Visual cleanup removes only tiny almost-collinear jitter.
If uncertain, points are kept.

DEPENDENCIES / LIMITATIONS
--------------------------
The backend ZIP supplied for this rebuild did not include integration/building_navigation.db or the f0..f7 SVG map directories referenced by backend/main.py. Therefore syntax/API compatibility could be tested, but live route generation and per-floor visual wall-crossing inspection could not be executed from the supplied ZIP alone.

When those existing project assets are present in their normal locations, no frontend code change is needed.

BACKEND / DATABASE CHANGES
--------------------------
No backend/database change is required for this frontend.

No source SVG modification is required for functionality. The frontend styles the served SVG in-browser and keeps all database/SVG coordinates untouched.


2.5D MAP PRESENTATION
---------------------
- Live floor SVGs now receive raised wall sides, adaptive wall depth, elevated
  room/facility shadows, a subtle perspective tilt, and an ambient floor shadow.
- The effect is presentation-only: the floor SVG source, backend route points,
  checkpoint order, and database coordinates are unchanged.
- Wall depth scales from each SVG viewBox so the differently scaled third-floor
  source remains visually consistent with the other floors.


PATCH v8.1 — Cross-floor connector hand-off
- Confirming a lift/stair checkpoint now automatically switches the map to the next routed floor.
- Progress remains anchored to the last manually confirmed checkpoint until the arrival checkpoint is tapped.


SCHEMATIC MAP v9
----------------
The frontend now semantically fills identifiable closed room/facility SVG shapes:
classrooms green, labs blue, offices/faculty yellow, lifts purple, stairs warm
orange/grey, bathrooms teal, utilities grey, and open/courtyard areas green.
Labels use a room/name + type treatment and bathrooms use the restroom symbol.

Safety rule: the frontend does not invent room polygons. If a supplied floor SVG
does not expose a safely identifiable closed shape for a room, that room remains
unfilled rather than drawing an overlay that could cross a wall. Floor-specific
manual polygons can only be authored after the actual f0-f7 SVG files are supplied.
Routing coordinates and A* geometry are never changed.


SCHEMATIC MAP v10 — ACTUAL SVG INSPECTION
-----------------------------------------
This release was built after inspecting all eight supplied floor SVGs individually.
The SVGs expose MAP-Walls, MAP-Rooms, MAP-Infrastructure, NAV-Nodes and NAV-Edges
layers. The MAP-Rooms layers primarily contain labels rather than closed room
polygons, so simply recoloring that layer cannot fill the rooms.

v10 therefore includes frontend-only floor-specific safe room polygons generated
from enclosed wall geometry around room labels. Only confidently enclosed regions
are filled; ambiguous/leaky regions are intentionally left unfilled rather than
risking overlap through a wall. Runtime /locations metadata determines semantic
class (classroom/lab/office/bathroom/utility/open area). Routing/A* coordinates
are unchanged.

The supplied source SVGs are included under assets/source-floor-svgs for audit.
