# Build from the REPO ROOT so this Dockerfile can see data/schema.json:
#   docker build -f service/Dockerfile -t parser-service:v1 .
FROM python:3.11-slim

WORKDIR /app

COPY service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY service/app.py .
COPY data/schema.json .

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
