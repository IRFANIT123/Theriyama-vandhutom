# Navora frontend — redesign pass

Backend untouched. `backend/main.py` and every API contract are byte-identical
to what you supplied. No route, checkpoint, or coordinate logic was changed.

## Files changed

| File | Change |
|---|---|
| `style.css` | Rewritten. Was 2092 lines in 5 stacked override passes (route line styled 3×, `:root` redefined mid-file). Now one organised pass with an indigo design system. |
| `index.html` | Restructured. Every element ID `app.js` binds to is preserved. |
| `app.js` | Targeted edits only — listed below. Routing, state, SVG projection, pan/zoom and blueprint decoration are unchanged. |
| `schematic-overlays.js` | Untouched. |

## Functional bugs fixed

1. **Pass-through floors rendered nothing.** `drawRouteOverlay` only drew a
   polyline at `length >= 2`. A floor the route crosses via a lift has exactly
   one point, so G→F4 showed an empty plan on F1, F2 and F3. Now those floors
   draw a connector callout with the next action.
2. **Route framed as a speck.** `focusRoutePreview` clamped zoom-out at `0.78`,
   fitting the whole floor plan. Reframed around the actual route segment, with
   a bias so the dock never covers it.
3. **Arrival collapsed into "current position".** Standing on the destination
   rendered the generic current-position marker. Now a distinct arrived state.
4. **Endless spinner when the backend is down.** The map area now explains it.
5. **Two floor selectors** (`#floorButtons` + `#floorOverviewButtons`). Reduced
   to one rail; `renderFloorButtons` guards the removed node.
6. **Mobile was a scrolling page**, not an app shell. Now a fixed shell: map
   dominant, planner as a sheet, dock as a bottom sheet.

## UX additions

- Next node carries two offset breathing rings — the most prominent map element.
- Tapping a node plays a one-shot green completion flash, then settles into the
  current-position marker.
- `Point 4 of 13 · 9 to go`, straight from the backend `checkpoint` numbering.
- Map palette desaturated to cool low-chroma tones so the indigo route is the
  only saturated thing on screen. This is the main legibility lever.
- 2D is now the default view; 2.5D remains on the toggle.
- Legend collapsed by default instead of permanently covering the map.
- Blocked-connector notice mirrored into the live route summary.

## Verified

53 automated checks pass at 1440×900 and 390×844 (`devfixture/verify.py`):
boot, search, route generation, walking the full 13-point route by tapping map
nodes *and* the dock button, pass-through floors, arrival, undo, clear, exit
routing, mid-route reroute with a blocked lift, keyboard reachability, ARIA
state, `prefers-reduced-motion`, and backend-offline handling.

## Not verified

Real touch hardware, and your real `building_navigation.db`. See
`devfixture/README.md`.
