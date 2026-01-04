# Frontend Dockerfile for Railway
FROM node:22-slim

WORKDIR /app

# Install dependencies
COPY package*.json ./
RUN npm install

# Copy source
COPY . .

# Build
RUN npm run build

# Railway provides PORT env var
ENV PORT=4321
ENV HOST=0.0.0.0

EXPOSE 4321

# Run the standalone Node server
CMD ["node", "./dist/server/entry.mjs"]
