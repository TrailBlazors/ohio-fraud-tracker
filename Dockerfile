# Railway Dockerfile - API only
FROM python:3.13-slim

WORKDIR /app

# Copy and install API dependencies
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy API code
COPY api/app app/

# Railway provides PORT env var
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
