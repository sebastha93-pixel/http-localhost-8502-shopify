"""
backend.main — Entrypoint del API FastAPI de MALE'DENIM OS.

Uso local:
    uvicorn backend.main:app --reload --port 8000

Uso Railway:
    uvicorn backend.main:app --host 0.0.0.0 --port $PORT

Docs interactivas:
    http://localhost:8000/docs       (Swagger)
    http://localhost:8000/redoc      (ReDoc)
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.core.config import settings
from backend.api import auditoria, auth, bot, clientes, comercial, conciliacion, dashboard, finanzas, health, historico, inventario, melonn, meta, metricas, pedidos, revenue
from backend.services import usuarios as usuarios_svc
from backend.core.security import hash_password
from backend.core import scheduler
from backend.core import bot_scheduler
from backend.core import revenue_scheduler


# ── Lifespan: bootstrap / cleanup ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print(f"🚀 MALE'DENIM OS API · env={settings.env}")
    print(f"   CORS allowed: {settings.cors_origins_list}")

    # Bootstrap del primer admin si la tabla usuarios está vacía
    try:
        if (
            settings.auth_bootstrap_email
            and settings.auth_bootstrap_password
            and usuarios_svc.contar() == 0
        ):
            usuarios_svc.crear(
                email=settings.auth_bootstrap_email,
                nombre=settings.auth_bootstrap_nombre,
                password_hash=hash_password(settings.auth_bootstrap_password),
                rol="admin",
            )
            print(f"   👤 Bootstrap admin creado: {settings.auth_bootstrap_email}")
    except Exception as e:
        print(f"   ⚠️  Bootstrap admin omitido: {e}")

    # Arrancar scheduler de refresh automático (cada 15 min por default)
    try:
        scheduler.start()
        print(f"   ⏱️  Scheduler activo · refresh cada {scheduler.REFRESH_INTERVAL_SECONDS}s")
    except Exception as e:
        print(f"   ⚠️  Scheduler no arrancó: {e}")

    # Cron del bot scraper (solo si BOT_AUTO_ENABLED=true)
    try:
        bot_scheduler.start()
    except Exception as e:
        print(f"   ⚠️  Bot scheduler no arrancó: {e}")

    # Cron nocturno del módulo Revenue (rankings)
    try:
        if revenue_scheduler.start():
            print(f"   📊 Revenue cron activo · hora objetivo {revenue_scheduler.HORA_OBJETIVO_BOG}am Bogotá")
    except Exception as e:
        print(f"   ⚠️  Revenue scheduler no arrancó: {e}")

    yield
    # Shutdown
    scheduler.stop()
    bot_scheduler.stop()
    revenue_scheduler.stop()
    print("👋 API detenida")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="MALE'DENIM OS · API",
    description="Backend del sistema operativo de MALE'DENIM. "
                "Centraliza logística, conciliación, ventas y operación.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# ── CORS — permitir que el frontend Next.js consuma este API ──────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(melonn.router)
app.include_router(metricas.router)
app.include_router(pedidos.router)
app.include_router(finanzas.router)
app.include_router(auditoria.router)
app.include_router(conciliacion.router)
app.include_router(dashboard.router)
app.include_router(bot.router)
app.include_router(comercial.router)
app.include_router(inventario.router)
app.include_router(historico.router)
app.include_router(clientes.router)
app.include_router(revenue.router)
app.include_router(meta.router)


@app.get("/", include_in_schema=False)
def root():
    return {
        "name":    "MALE'DENIM OS API",
        "version": "0.1.0",
        "docs":    "/docs",
        "health":  "/api/health",
    }
