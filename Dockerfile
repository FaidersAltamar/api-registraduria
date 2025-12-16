FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

WORKDIR /app

# Instalar curl para health checks
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Copiar requirements
COPY requirements.txt .

# Instalar dependencias Python
RUN pip install --no-cache-dir -r requirements.txt

# Copiar aplicación
COPY app.py .

# Instalar navegadores de Playwright
RUN playwright install chromium
RUN playwright install-deps chromium

# Variables de entorno optimizadas
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PYTHONUNBUFFERED=1
ENV PORT=10000

# Health check más permisivo
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=5 \
  CMD curl -f http://localhost:10000/health || exit 1

# Exponer puerto
EXPOSE 10000

# Comando optimizado para Render/Railway
CMD ["gunicorn", "app:app", \
     "--bind", "0.0.0.0:10000", \
     "--workers", "1", \
     "--worker-class", "sync", \
     "--threads", "2", \
     "--timeout", "120", \
     "--graceful-timeout", "30", \
     "--keep-alive", "5", \
     "--log-level", "info", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--max-requests", "100", \
     "--max-requests-jitter", "10"]
