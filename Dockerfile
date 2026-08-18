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

# CHEQUEO DE IMPORT EN EL BUILD (no bloqueante).
#
# Por qué existe: el 2026-08-18 dos deploys seguidos fallaron sin escribir NI UNA
# línea en los logs de runtime — ni el echo del arranque. Sin traza no hay
# diagnóstico, y "reintentar a ver" cuesta 10 minutos por vuelta. Los logs de
# BUILD sí se leen siempre, así que el traceback se fuerza acá.
#
# `|| true` a propósito: importar la app en el build no tiene las variables de
# entorno de producción, así que un fallo acá NO significa código roto y no debe
# tumbar el build. Vale solo por el traceback que imprime.
RUN python -c "import backend.main" \
    && echo "SMOKE: backend.main importa OK" \
    || echo "SMOKE: backend.main NO importa en build (mirar el traceback de arriba)"

# Railway inyecta $PORT
ENV PORT=8080
EXPOSE 8080

# Entrypoint con multi-worker para 25+ usuarios simultáneos.
# WEB_CONCURRENCY (env var, default 4) controla número de workers Uvicorn.
# El primer worker que arranque toma el file lock /tmp/maledenim-leader.lock
# y se encarga de los schedulers/crons. Los demás workers solo sirven HTTP.
RUN printf '#!/bin/sh\nset -e\nWORKERS="${WEB_CONCURRENCY:-4}"\necho "Arrancando con $WORKERS workers Uvicorn"\nrm -f /tmp/maledenim-leader.lock\nexec uvicorn backend.main:app --host 0.0.0.0 --port "${PORT:-8080}" --workers "$WORKERS"\n' > /app/start.sh \
    && chmod +x /app/start.sh

CMD ["/app/start.sh"]
