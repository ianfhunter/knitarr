FROM node:20-bookworm-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/knitarr ./knitarr
COPY --from=frontend /frontend/dist ./knitarr/static
COPY samples ./samples

ENV KNITARR_DATA_DIR=/data \
    KNITARR_DB_PATH=/data/knitarr.db \
    KNITARR_LIBRARY_DIR=/data/library

RUN mkdir -p /data/library

EXPOSE 8765

CMD ["uvicorn", "knitarr.main:app", "--host", "0.0.0.0", "--port", "8765"]
