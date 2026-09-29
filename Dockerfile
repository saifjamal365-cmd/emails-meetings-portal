# One container: the FastAPI backend also serves the built React portal.
#   docker build -t email-meeting-portal .
#   docker run -p 8000:8000 --env-file backend/.env -v portal-data:/data email-meeting-portal

# ---- 1. Build the React portal ----------------------------------------------------------
FROM node:22-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- 2. Python backend + the built portal -----------------------------------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENVIRONMENT=production \
    DATA_DIR=/data
WORKDIR /app/backend
COPY backend/pyproject.toml ./
COPY backend/app ./app
RUN pip install --no-cache-dir .
COPY --from=frontend /app/frontend/dist /app/frontend/dist
RUN mkdir -p /data
EXPOSE 8000

# One process only: the background jobs and the login limits live in this process.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
