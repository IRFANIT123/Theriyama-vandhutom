# Field Trace design system

CampusNav is a working field plan, not a generic dashboard. The floor plan is the primary surface; every surrounding control should help someone establish a route, understand their current position, or take the next physical action.

## Visual language

- Use drafting-paper cream for the canvas and panels, ink navy for primary type and structure, graphite for secondary information, survey orange for routes and committed actions, and teal only for the current position.
- Preserve the ruled route planner, eight-floor binding, measured grid, technical annotations, and square drafting controls. Avoid gradients, glossy effects, decorative cards, oversized radii, and interchangeable SaaS-dashboard styling.
- Keep the map visually dominant. Navigation chrome should feel indexed onto the plan rather than floating above it.
- Use self-hosted Fira Sans Condensed at 600/700 for headings, labels, metrics, buttons, and wayfinding text. Use Segoe UI for longer body copy and accessible fallbacks.

## Layout and behavior

- Desktop begins in planning mode with a slim left route sheet, central map, right-side floor index, top utility rail, and a bottom next-action area. After routing, transform the planner into route status and instructions; do not replace the map.
- Mobile uses horizontal floor tabs, a compact active-route summary, and an explicit Route details toggle. Keep the map in the first viewport once a route is active. The fixed bottom tray owns the immediate instruction and I’m here / Blocked actions.
- The mobile route map starts closer for legibility, remains pannable and zoomable, and keeps relevant room/facility labels between 11–16 px.
- Route changes are whole-interface state changes. Orange communicates the chosen path or commitment; teal communicates present location. Do not use color alone for status.

## Component rules

- Controls are rectangular with 0–4 px radii, one-pixel ink/graphite borders, compact uppercase labels, and clear keyboard focus rings.
- Panels use borders and subtle inset rules instead of elevation. Shadows are reserved for fixed or spatially raised navigation surfaces.
- Use a 4 px spacing base. Prefer 8, 12, 16, 24, and 32 px gaps; keep route data dense without reducing interactive targets below 44 px on touch devices.
- Motion should explain state change: 120–220 ms, ease-out, opacity/transform only. Respect `prefers-reduced-motion` and never animate map or route geometry gratuitously.

## Accessibility and responsive checks

- Maintain WCAG AA contrast, visible focus, semantic labels, and descriptive text for all icon-only actions.
- At 680 px and below, collapse active-route detail by default, keep its toggle reachable, enlarge map labels, and reserve bottom space for the fixed action tray.
- At 1180 px and below, simplify secondary desktop chrome before reducing map area. Test idle and active routes at 390×844 and 1440×900, including long destination and instruction strings.
