# Deploy en Railway — MALE'DENIM OS

Esta guía describe cómo desplegar este repositorio en Railway.

## Pre-requisitos

- Cuenta en [Railway](https://railway.app/) (plan Hobby: $5/mes)
- Acceso al repo GitHub (`sebastha93-pixel/http-localhost-8502-shopify`)
- El archivo local `.streamlit/secrets.toml` con todas las credenciales

## Pasos

### 1. Crear el proyecto en Railway

1. Entra a https://railway.app/new
2. Elige **Deploy from GitHub repo**
3. Autoriza Railway a leer tu cuenta GitHub
4. Selecciona el repo `http-localhost-8502-shopify`
5. Railway detecta automáticamente:
   - `runtime.txt` → Python 3.11.9
   - `requirements.txt` → dependencias
   - `Procfile` → comando de inicio
   - `railway.toml` → config adicional

### 2. Pegar variables de entorno

Una vez creado el servicio, ve a **Variables** y pega TODAS las siguientes.

#### APIs externas

```
MELONN_API_KEY            = <el valor de tu secrets.toml>
SHOPIFY_STORE             = male-denim-5524.myshopify.com
SHOPIFY_ACCESS_TOKEN      = <el valor de tu secrets.toml>
SHOPIFY_API_VERSION       = 2024-01
MP_ACCESS_TOKEN           = <el valor de tu secrets.toml>
SUPABASE_URL              = https://vmuopwdswrpimkijosyb.supabase.co
SUPABASE_KEY              = <el valor de tu secrets.toml>
```

#### Auth + usuarios (RECOMENDADO: usar STREAMLIT_SECRETS_TOML)

Copia el contenido COMPLETO de tu `.streamlit/secrets.toml` local en
una sola variable llamada `STREAMLIT_SECRETS_TOML`. Railway soporta
multi-línea. Ejemplo:

```toml
MELONN_API_KEY = "ABC..."
SHOPIFY_STORE = "..."
SHOPIFY_ACCESS_TOKEN = "..."
SHOPIFY_API_VERSION = "2024-01"
MP_ACCESS_TOKEN = "..."
SUPABASE_URL = "..."
SUPABASE_KEY = "..."

[cookie]
name = "maledenim_auth"
key = "tu-clave-aleatoria-de-32-chars"
expiry_days = 30

[credentials.usernames.sebastian]
name = "Sebastián Hurtado"
email = "sebastian@example.com"
password = "$2b$12$..."   # hash bcrypt
role = "admin"
permisos = ["logistica","comercial","mercadopago","conciliacion"]
```

> El script `bootstrap_secrets.py` se ejecuta antes de Streamlit y
> regenera `.streamlit/secrets.toml` desde esta variable.

### 3. Generar dominio público

1. Ve a **Settings → Networking**
2. Click **Generate Domain**
3. Railway te da una URL tipo `tu-app-production.up.railway.app`

### 4. Deploy

Railway desplega automáticamente al hacer push a `main` en GitHub.
El primer deploy puede tomar 3-5 minutos (instala dependencias).

### 5. Verificación post-deploy

Abre la URL pública y verifica:

- [ ] Login carga correctamente
- [ ] Después de login, ves Centro de Control
- [ ] Sidebar muestra los 5 grupos (Operaciones, Finanzas, Comercial, Inteligencia, Configuración)
- [ ] VENTAS HOY muestra valor real de Shopify
- [ ] `/integraciones` → todas las APIs en verde

## Estructura de archivos para Railway

```
maledenim-os/
├── Procfile                  # web: python bootstrap_secrets.py && streamlit run ...
├── runtime.txt               # python-3.11.9
├── requirements.txt          # Dependencias
├── railway.toml              # Config builder + restart policy
├── bootstrap_secrets.py      # Genera .streamlit/secrets.toml desde env vars
├── .env.example              # Ejemplo de env vars
├── dashboard/                # Streamlit app
├── src/                      # Clientes API + lógica
└── data/                     # SQLite local (se regenera; no se persiste)
```

## Variables persistentes (opcional)

Si quieres mantener el SQLite local (`data/db/maledenim.db`) entre
deploys, en Railway:

1. Ve a **Settings → Volumes**
2. Click **Add Volume**
3. Mount path: `/app/data/db`
4. Size: 1 GB

> Esto es opcional. El caché real vive en Supabase (`melonn_cache`).
> SQLite es solo fallback local.

## Costos esperados

Plan Hobby: $5/mes mínimo (incluye créditos para una app de este tamaño).
Si la app está prendida 24/7 y procesa pedidos cada 30 min, costo real
estimado: **$5–10/mes**.

## Troubleshooting

| Síntoma | Causa | Fix |
|---------|-------|-----|
| Build falla con "Python version not found" | runtime.txt incorrecto | Usar `python-3.11.9` exacto |
| App arranca pero "secrets file not found" | bootstrap_secrets.py no encontró STREAMLIT_SECRETS_TOML | Pegar la env var |
| Login dice "Usuario incorrecto" | Hash bcrypt no coincide | Verificar comillas en el TOML |
| Pedidos Melonn no cargan | MELONN_API_KEY no setea | Verificar env var |
| App carga pero está lenta primera vez | Cache Supabase vacío | Normal — el primer fetch tarda 30s, después es instantáneo |

## Migrar desde Streamlit Cloud

Si tu app está actualmente en Streamlit Cloud:

1. **NO borres** la app de Streamlit Cloud hasta confirmar que Railway funciona
2. Sigue los pasos 1-4 de esta guía
3. Cuando Railway esté estable, apunta tu dominio personalizado a Railway
4. Una vez funcione todo, puedes pausar la app de Streamlit Cloud

## Soporte

- Railway docs: https://docs.railway.app/
- Streamlit docs: https://docs.streamlit.io/
- Para issues específicos del proyecto: revisar logs en Railway → Deployments
