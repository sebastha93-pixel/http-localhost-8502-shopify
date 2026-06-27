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

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.core.config import settings
from backend.api import auditoria, auth, bot, clientes, cod_acciones, comercial, conciliacion, dashboard, finanzas, health, historico, inventario, melonn, meta, metricas, pedidos, revenue
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
        elif settings.auth_bootstrap_email:
            # Self-healing: si el bootstrap user existe pero no es admin, promoverlo
            existing = usuarios_svc.obtener_por_email(settings.auth_bootstrap_email)
            if existing and existing.get("rol") != "admin":
                usuarios_svc.actualizar(existing["id"], rol="admin", activo=True)
                print(f"   ⬆️  Bootstrap admin promovido: {settings.auth_bootstrap_email}")
    except Exception as e:
        print(f"   ⚠️  Bootstrap admin omitido: {e}")

    # Schedulers/crons: con múltiples workers Uvicorn cada uno corre lifespan.
    # Solo UNO debe correr los crons (auditorías, sync_tasks, transcripción).
    # Mecanismo: file lock atómico — el primer worker que cree el archivo gana.
    LEADER_LOCK = "/tmp/maledenim-leader.lock"
    es_lider = False
    try:
        # O_EXCL atomic: falla si el archivo ya existe (otro worker ganó).
        fd = os.open(LEADER_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, f"pid={os.getpid()}".encode())
        os.close(fd)
        es_lider = True
        print(f"   👑 Worker {os.getpid()} es LÍDER (corre schedulers)")
    except FileExistsError:
        es_lider = False
        print(f"   🤝 Worker {os.getpid()} es seguidor (solo sirve HTTP)")
    except Exception as e:
        # Fallback conservador: si falla el lock por permisos u otro motivo,
        # asume líder si WEB_CONCURRENCY=1, no-líder si >1.
        es_lider = int(os.environ.get("WEB_CONCURRENCY", "1")) <= 1
        print(f"   ⚠️  Lock fallback (es_lider={es_lider}): {e}")

    if es_lider:
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
    else:
        print(f"   ⊘ Schedulers desactivados en este worker (WORKER_ROLE != leader)")

    # Cron nocturno del módulo Revenue (rankings) — también solo en lider
    if es_lider:
        try:
            if revenue_scheduler.start():
                print(f"   📊 Revenue cron activo · hora objetivo {revenue_scheduler.HORA_OBJETIVO_BOG}am Bogotá")
        except Exception as e:
            print(f"   ⚠️  Revenue scheduler no arrancó: {e}")

        # One-time backfill: extraer custom_fields_values del raw JSONB
        # a las columnas dedicadas. Idempotente — marca done en sync_state
        # cuando termina para no repetir en cada arranque.
        try:
            from backend.services import revenue_db as _rdb
            done = _rdb.leer_sync_state("custom_fields_backfill_done")
            if done != "1":
                import threading
                def _do_backfill():
                    print(f"   🔄 Backfill custom_fields arrancando en background...")
                    total = 0
                    last_id = 0
                    for i in range(200):  # max 200 lotes de 1000 = 200k leads
                        try:
                            res = _rdb.backfill_custom_fields(limit=1000, start_lead_id=last_id)
                        except Exception as e:
                            print(f"   ⚠️  Backfill error: {e}")
                            break
                        if not res.get("ok"): break
                        proc = res.get("procesados", 0)
                        enr = res.get("enriquecidos", 0)
                        new_last = res.get("last_lead_id", 0)
                        total += enr
                        print(f"   🔄 Backfill lote {i+1}: proc={proc} enriq={enr} last_id={new_last}")
                        if proc == 0 or new_last <= last_id:
                            break  # no más leads o no avanzamos = terminamos
                        last_id = new_last
                    _rdb.guardar_sync_state("custom_fields_backfill_done", "1")
                    print(f"   ✅ Backfill custom_fields TERMINADO. Total enriquecidos: {total}")
                t = threading.Thread(target=_do_backfill, daemon=True, name="cf_backfill")
                t.start()
                print(f"   🔄 Backfill custom_fields encolado (background)")
            else:
                print(f"   ✓ Backfill custom_fields ya estaba hecho")
        except Exception as e:
            print(f"   ⚠️  Backfill bootstrap: {e}")

    yield
    # Shutdown
    if es_lider:
        scheduler.stop()
        bot_scheduler.stop()
        revenue_scheduler.stop()
        try:
            os.unlink(LEADER_LOCK)
        except Exception:
            pass
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
app.include_router(cod_acciones.router)


@app.get("/", include_in_schema=False)
def root():
    return {
        "name":    "MALE'DENIM OS API",
        "version": "0.1.0",
        "docs":    "/docs",
        "health":  "/api/health",
    }
