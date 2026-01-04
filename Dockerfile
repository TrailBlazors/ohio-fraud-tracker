# Railway Dockerfile - Combined API + Static Frontend
FROM python:3.13-slim

WORKDIR /app

# Install Node.js for building frontend
RUN apt-get update && \
    apt-get install -y nodejs npm && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Build frontend as static files
COPY frontend/package*.json frontend/
RUN cd frontend && npm install

COPY frontend/ frontend/
RUN cd frontend && npm run build

# Copy API code
COPY api/app app/
COPY api/scripts scripts/

# Move built static files to where FastAPI expects them
RUN mkdir -p static && cp -r frontend/dist/* static/

# Expose port (Railway sets PORT env var)
EXPOSE 8000

# Start uvicorn directly (simpler, more reliable)
CMD ["sh", "-c", "python -m scripts.refresh_stats || true && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
