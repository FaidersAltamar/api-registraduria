FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

WORKDIR /app

# Instalar curl
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

# Variables de entorno
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PYTHONUNBUFFERED=1
ENV PORT=10000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=5 \
  CMD curl -f http://localhost:10000/health || exit 1

# Exponer puerto
EXPOSE 10000

# IMPORTANTE: Usar waitress en lugar de gunicorn
# Waitress es single-threaded y funciona mejor con Playwright
CMD ["python", "-m", "waitress", "--host=0.0.0.0", "--port=10000", "--threads=1", "app:app"]
