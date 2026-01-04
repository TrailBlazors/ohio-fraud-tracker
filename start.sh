#!/bin/bash
echo "Refreshing stats cache..."
python -m scripts.refresh_stats || echo "Cache refresh skipped"
echo "Starting server on port ${PORT:-8000}..."
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
