FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

WORKDIR /app

# Variables de entorno para optimización
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Instalar solo chromium
RUN playwright install chromium --with-deps

# Health check más tolerante
HEALTHCHECK --interval=60s --timeout=30s --start-period=90s --retries=2 \
  CMD python -c "import requests; requests.get('http://localhost:10000/health', timeout=10)" || exit 1

# Timeouts más largos y keepalive
CMD ["gunicorn", "app:app", \
     "--bind", "0.0.0.0:10000", \
     "--workers", "1", \
     "--threads", "1", \
     "--timeout", "150", \
     "--graceful-timeout", "150", \
     "--keep-alive", "120", \
     "--worker-class", "sync", \
     "--preload", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--log-level", "info"]
