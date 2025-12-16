FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

WORKDIR /app

# Copiar requirements e instalar
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar app
COPY app.py .

# Instalar chromium
RUN playwright install chromium
RUN playwright install-deps chromium

# Variables de entorno
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:10000/health')" || exit 1

# Comando con timeouts más largos
CMD ["gunicorn", "app:app", \
     "--bind", "0.0.0.0:10000", \
     "--workers", "1", \
     "--threads", "1", \
     "--timeout", "120", \
     "--graceful-timeout", "120", \
     "--keep-alive", "5", \
     "--worker-class", "sync", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--log-level", "info"]
