FROM --platform=linux/arm64 public.ecr.aws/docker/library/python:3.13.15-slim

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends libexpat1 \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd -r -s /bin/false appuser && chown -R appuser /app
USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/ping')"]

CMD ["opentelemetry-instrument", "python", "app.py"]
