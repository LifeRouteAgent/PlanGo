FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV LIFEROUTE_CONFIG_PATH=/app/config.docker.json

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

EXPOSE 8000

CMD ["sh", "-c", "python scripts/init_runtime_schema.py && uvicorn app.api.main:app --host 0.0.0.0 --port 8000"]
