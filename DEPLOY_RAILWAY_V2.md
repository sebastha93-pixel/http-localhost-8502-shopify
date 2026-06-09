# Deploy en Railway — Stack nuevo (FastAPI + Next.js)

El stack v2 corre **en paralelo** al Streamlit actual durante la migración.
Mismo proyecto Railway, mismo repo, **3 servicios independientes**.

## Servicios

| Servicio | Path | Stack | Estado |
|---|---|---|---|
| `streamlit` (existente) | `/` (raíz) | Streamlit | sigue corriendo igual |
| `backend` (nuevo) | `/` (raíz) | FastAPI | crear |
| `frontend` (nuevo) | `/frontend` | Next.js | crear |

---

## 1) Crear servicio `backend` (FastAPI)

Railway → proyecto → **New → GitHub Repo** → mismo repo

Settings del servicio:
- **Root Directory**: `/` (raíz — necesita acceso a `src/`)
- **Build Command**: (vacío — nixpacks usa `requirements.txt` raíz)
- **Start Command**:
  ```
  uvicorn backend.main:app --host 0.0.0.0 --port $PORT
  ```
- **Healthcheck Path**: `/api/health`

**Variables de entorno** (copiar las mismas del servicio Streamlit):
```
MELONN_API_KEY=...
SHOPIFY_STORE=...
SHOPIFY_ACCESS_TOKEN=...
SHOPIFY_API_VERSION=2024-01
MP_ACCESS_TOKEN=...
SUPABASE_URL=...
SUPABASE_KEY=...
AUTH_JWT_SECRET=<generar uno nuevo, 32+ chars random>
CORS_ORIGINS=https://<tu-frontend>.up.railway.app
ENV=production
```

Generar dominio público en Settings → Networking → Generate Domain.
Ejemplo: `male-denim-api.up.railway.app`

Verificar:
```
GET https://male-denim-api.up.railway.app/api/health
→ { "status": "ok", "env": "production", ... }
```

---

## 2) Crear servicio `frontend` (Next.js)

Railway → **New → GitHub Repo** → mismo repo

Settings del servicio:
- **Root Directory**: `frontend`
- **Build Command**: `npm install && npm run build`
- **Start Command**: `npm start`
- **Healthcheck Path**: `/`

**Variables de entorno:**
```
NEXT_PUBLIC_API_URL=https://male-denim-api.up.railway.app
NODE_ENV=production
```

Generar dominio público.
Ejemplo: `male-denim.up.railway.app`

---

## 3) Actualizar CORS del backend

Volver al servicio `backend` y poner el dominio del frontend en `CORS_ORIGINS`:
```
CORS_ORIGINS=https://male-denim.up.railway.app,http://localhost:3000
```

Railway redeploya automáticamente.

---

## 4) Validación final

Abrir el frontend en el navegador. Debe cargar:
- `/centro-control` — 5 KPIs con data real
- `/logistica` — tabla con todos los pedidos
- `/contraentrega`, `/envios`, `/devoluciones`, `/incidencias`

Si el frontend muestra "Error al cargar datos" → revisar:
1. `NEXT_PUBLIC_API_URL` apunta al backend correcto
2. `CORS_ORIGINS` del backend incluye el dominio del frontend
3. `/api/health/config` del backend muestra `melonn: true` y `supabase: true`

---

## Plan de corte (cuando v2 esté validado)

1. Apuntar dominio principal (si aplica) al servicio `frontend`
2. Pausar el servicio `streamlit` (no eliminar inmediatamente — backup)
3. Tras 1–2 semanas sin issues, eliminar `streamlit`
