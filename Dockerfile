FROM python:3.12-slim

  ENV PYTHONDONTWRITEBYTECODE=1 \
      PYTHONUNBUFFERED=1 \
      PIP_NO_CACHE_DIR=1

  WORKDIR /app

  COPY platform/requirements.txt /app/platform/requirements.txt
  RUN pip install --upgrade pip && pip install -r /app/platform/requirements.txt

  COPY . /app

  CMD ["sh", "-c", "uvicorn --app-dir platform cbcr_backend:app --host 0.0.0.0 --port ${PORT:-8000}"]
