# CampusNav Product Context

## Product

CampusNav is an indoor wayfinding application for PRP E Block at VIT Vellore. It helps people find rooms and facilities across the Ground Floor and Floors 1–7 while preserving the building's authoritative routing graph and floor geometry.

## People and setting

- Primary users: students navigating to classrooms, labs, offices, lifts, stairs, bathrooms, entrances, and exits.
- Secondary users: staff and visitors who may not know internal room or entrance identifiers.
- Operating context: movement through a real multi-floor academic building, often while carrying a phone; desktop/laptop remains the primary demonstration surface.
- Users need fast visual orientation and plain-language directions. They should not need to understand navigation nodes, edge IDs, or database codes.

## Core outcomes

1. Search for a room or facility by an understandable name or number.
2. Select a start and destination and choose lift or stairs for multi-floor travel.
3. Follow an accurate route on the real floor plan, with the current position, remaining path, destination, and floor changes kept clear.
4. Manually confirm checkpoints indoors, move back to the previous checkpoint after an accidental confirmation, and retain correct route progress.
5. Find a building exit without knowing an entrance database ID.
6. Reroute around a lift or stair that is unavailable.
7. Use outdoor GPS only to identify the nearest entrance; continue with manual checkpoint navigation indoors.

## Product rules that future work must preserve

- The backend route calculation, A* behavior, databases, nodes, edges, route coordinates, floor SVG geometry, and integration data are authoritative.
- Presentation may suppress redundant visual markers but must retain every authoritative route point in the route line.
- The floor plan, corridor, active route, checkpoints, current marker, and destination marker must share one coordinate system.
- Technical graph nodes and unused edges are implementation details and must not be exposed to users.
- Corridors represent walkable architectural areas, not the navigation graph.
- Checkpoint interaction must work with mouse and touch and must not be swallowed by map pan/drag behavior.
- Indoor progress is user-confirmed because reliable indoor GPS is not available.
- Ground-floor entrances act as exits; the product must expose human-readable exit choices.
- All eight floors (G, F1–F7), multi-floor continuation, blocked connectors, search, and outdoor nearest-entrance behavior are required capabilities.
- Accessibility, legible labels, and a usable mobile layout are required even though desktop/laptop is the primary demo target.

## Voice and terminology

- Use concise, reassuring, action-oriented language.
- Prefer room and facility names that people recognize: “Room 234,” “Lift 2,” “Stair 3,” “Nearest Exit.”
- Prefer “You are here,” “Current Point,” “Previous Point,” and “Destination” over technical navigation terminology.
- Explain errors and unavailable routes in plain language and offer the next useful action.

## Evidence and source of truth

- Real floor geometry: the existing G and F1–F7 SVG files and supplied architectural blueprints.
- Routing and progress behavior: the existing FastAPI backend and navigation database.
- Product acceptance criteria: the final CampusNav implementation brief supplied on 2026-09-16.

## Unresolved product decisions

- Whether the production deployment will require authentication or role-specific experiences.
- Whether future indoor positioning hardware will supplement manual checkpoint confirmation.
- Which accessibility languages beyond English are required for deployment.
