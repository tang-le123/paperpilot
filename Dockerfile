ARG NODE_IMAGE=node:22-alpine
ARG PYTHON_IMAGE=python:3.12-slim
ARG PIP_INDEX_URL=https://pypi.org/simple

FROM ${NODE_IMAGE} AS frontend

WORKDIR /app/frontend_react
COPY frontend_react/package*.json ./
RUN npm ci
COPY frontend_react/ ./
RUN npm run build


FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/backend

WORKDIR /app

# pymupdf / rapidocr runtime libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

ARG PIP_INDEX_URL=https://pypi.org/simple
COPY requirements.txt .
RUN pip install --upgrade pip --index-url ${PIP_INDEX_URL} && \
    pip install -r requirements.txt --index-url ${PIP_INDEX_URL}
COPY backend ./backend
COPY --from=frontend /app/frontend_react/dist ./frontend_react/dist
COPY knowledge ./knowledge
COPY eval ./eval
COPY README.md .

RUN mkdir -p /app/data/uploads /app/data/chroma

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
