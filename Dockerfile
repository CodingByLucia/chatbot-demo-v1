# Stage 1: build the React UI into static files
FROM node:22-alpine AS ui
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: python runtime, ships without node
FROM python:3.13-slim
WORKDIR /code
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ app/
COPY docs/ docs/
COPY --from=ui /build/dist frontend/dist

# Render injects $PORT; 8000 is only the local `docker run` fallback
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
