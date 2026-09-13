FROM python:3.11-slim AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi==0.115.* uvicorn[standard]==0.30.* \
    aiokafka==0.11.* asyncpg==0.30.* redis==5.* \
    pydantic==2.* gremlinpython==3.7.* clickhouse-driver==0.2.*

COPY . /app/journey-service
WORKDIR /app/journey-service

EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
