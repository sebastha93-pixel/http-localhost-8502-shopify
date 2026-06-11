# Dockerfile del backend — imagen oficial de Playwright con Chromium + libs
# Ya incluye todas las dependencias del sistema (libglib, nss, etc.)
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

WORKDIR /app

# Dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Asegurar que Chromium está instalado (la imagen base ya lo trae, pero por si acaso)
RUN python -m playwright install chromium

# Código de la app
COPY . .

# Railway inyecta $PORT
ENV PORT=8080
EXPOSE 8080

# Entrypoint script garantiza expansión de $PORT incluso si Railway
# pasa el comando sin shell.
RUN printf '#!/bin/sh\nexec uvicorn backend.main:app --host 0.0.0.0 --port "${PORT:-8080}"\n' > /app/start.sh \
    && chmod +x /app/start.sh

CMD ["/app/start.sh"]
