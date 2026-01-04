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

# Move built static files
RUN mkdir -p static && cp -r frontend/dist/* static/

# Create startup script
RUN echo '#!/bin/bash\n\
echo "Refreshing stats cache..."\n\
python -m scripts.refresh_stats || echo "Cache refresh skipped"\n\
echo "Starting server..."\n\
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}' > /app/start.sh && \
    chmod +x /app/start.sh

CMD ["/app/start.sh"]
