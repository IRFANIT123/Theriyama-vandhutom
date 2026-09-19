#!/bin/bash
# DEV-ONLY: start backend (8000) + static frontend (5500) detached.
cd /home/claude/prp/work
pkill -f "uvicorn backend.main" 2>/dev/null
pkill -f "http.server 5500" 2>/dev/null
sleep 1
setsid nohup python3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 > /tmp/api.log 2>&1 < /dev/null &
setsid nohup python3 -m http.server 5500 --directory frontend --bind 127.0.0.1 > /tmp/web.log 2>&1 < /dev/null &
for i in $(seq 1 30); do
  curl -sf localhost:8000/health > /dev/null && curl -sf localhost:5500/ > /dev/null && break
  sleep 1
done
curl -s localhost:8000/health; echo
echo "frontend: $(curl -s -o /dev/null -w '%{http_code}' localhost:5500/)"
