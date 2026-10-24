FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Celesto SDK is optional for /health; needed only when the api creates guests (CELESTO_PROVIDER=cloud|local).
RUN pip install --no-cache-dir celesto || echo "celesto SDK not installed (jobs endpoint disabled)"
COPY app ./app
COPY grader ./grader
COPY reports ./reports
COPY logs ./logs
COPY seeds ./seeds
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${API_PORT:-8080}"]
