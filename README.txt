# CampusNav FastAPI Backend

Place this `backend` folder in the main project folder:

campus _ nav e block/
├── backend/
│   ├── __init__.py
│   └── main.py
├── integration/
│   └── building_navigation.db
├── f0/
├── ...
└── f7/

Install dependencies:

python -m pip install -r backend\requirements.txt

Run:

python -m uvicorn backend.main:app --reload

Open:

http://127.0.0.1:8000/docs

Recommended first route test:

start_floor = G
start = ENTRANCE1-G
destination_floor = F2
destination = 229
mode = stairs

Then test:

start_floor = G
start = G41
destination_floor = F7
destination = 740
mode = lift
