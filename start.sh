#!/bin/bash
# Start both API and Frontend

# Start API in background on port 8000
echo "Starting API server..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 &
API_PID=$!

# Wait for API to be ready
echo "Waiting for API..."
sleep 3

# Start Frontend on the Railway PORT (default 3000)
# Frontend will proxy /api requests to localhost:8000
echo "Starting Frontend server..."
cd frontend
PORT=${PORT:-3000} HOST=0.0.0.0 node ./dist/server/entry.mjs &
FRONTEND_PID=$!

# Handle shutdown
trap "kill $API_PID $FRONTEND_PID 2>/dev/null" EXIT

# Wait for any process to exit
wait -n

# Exit with status of process that exited first
exit $?
