---
version: 1
slug: "frontend-index-html"
primary_target: "frontend/index.html"
related_targets: ["frontend/style.css","frontend/app.js"]
---

# CampusNav main wayfinding surface

- Scope: `frontend/index.html` with `frontend/style.css` and the existing `frontend/app.js` interaction contract.
- Mode: Operate.
- Audience and job: students, staff, and visitors finding a room or exit while moving through PRP E Block, often one-handed on a phone.
- Primary task: choose From and To, get a valid route, understand the current floor and next physical action, then manually confirm checkpoints.
- Proof: the live authoritative floor SVG, real room/facility labels, all eight floors, route continuation, connector avoidance, and visible manual progress.
- Constraints: preserve backend routing, graph data, coordinates, source floor geometry, DOM IDs used by JavaScript, mouse/touch checkpoint behavior, and plain-language accessibility.

## Direction contract

THESIS: CampusNav is the working field plan carried through the building. The map is not content inside a dashboard; it is the surface itself, and route setup, floor state, and progress read as disciplined annotations on that surface. Refuse the generic white-card map dashboard.

OWN-WORLD: Matte drawing-film white, ink navy, graphite construction lines, survey orange for the one committing action, teal for current position, and quiet grey for completed work. Components feel indexed, stamped, ruled, and tactile without imitating CAD software.

STORY: The visitor identifies the building and floor, sets two human-readable locations, chooses lift or stairs, and receives one clear route. During travel, planning collapses behind the live instruction, current point, destination, progress, and floor handoff.

FIRST VIEWPORT: A slim indexed planner occupies the left edge while the live floor plan owns the remaining field. Oversized G/F1–F7 drawing tabs bind the right edge. A compact top project strip identifies PRP E Block. When active, the next instruction is stamped across the bottom with the primary confirmation at the far right.

FORM: Assigned grounded direction 3 of 7, “Field Trace,” seed key `d79b901a`. Signature interaction: beginning a route changes the entire page from plan setup to field guidance; confirming a checkpoint inks the next segment forward while completed state recedes to graphite. Responsive behavior preserves the map and turns the planner into a compact upper sheet with a thumb-height action dock.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Unresolved decisions

- Whether production should default to 2D or 2.5D map presentation.
- Whether future authentication will require role-specific tools in the project strip.
