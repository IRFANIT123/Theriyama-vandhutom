# devfixture — DEV ONLY, not part of the app

The backend ZIP supplied did not include `integration/building_navigation.db`
or the `f0`–`f7` floor folders that `backend/main.py` requires, so the app could
not be run — which is most likely why the route-rendering bugs survived several
earlier redesign passes.

`build_fixture_db.py` reconstructs a database with the **exact schema
`main.py` expects** from the `NAV - Nodes` / `NAV - Edges` / `MAP - Rooms`
layers already embedded in your real floor SVGs (421 nodes, 561 edges,
183 locations, 123 vertical connector edges).

This exists **only so the unmodified backend can be executed for frontend
verification**. Delete this folder and drop in your real database and floor
folders; nothing in `frontend/` references it.

    python3 devfixture/build_fixture_db.py   # rebuild the fixture DB
    ./devfixture/serve.sh                    # backend :8000 + frontend :5500
    python3 devfixture/verify.py             # 53-check end-to-end suite
