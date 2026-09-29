## gstack (recommended)

This project uses [gstack](https://github.com/garrytan/gstack) for AI-assisted workflows.
Install it for the best experience:

```bash
git clone --depth 1 https://github.com/garrytan/gstack.git ~/.claude/skills/gstack
cd ~/.claude/skills/gstack && ./setup --team
```

Skills like /qa, /ship, /review, /investigate, and /browse become available after install.
Use /browse for all web browsing. Use ~/.claude/skills/gstack/... for gstack file paths.

## Dev servers: matar por puerto, NUNCA por nombre

En este Mac corren varios dev servers de Next.js a la vez (POS :3077, MALE-CRM :3100, etc.).
**Prohibido `pkill -f "next dev"`, `pkill -f next` o `killall node`**: matan en silencio
los servers de los otros proyectos (así se tumbó 5+ veces el dev de MALE-CRM el 2026-08-12).
Para reiniciar el frontend del POS, matar SOLO el proceso de tu puerto:

```bash
kill $(lsof -ti:3077 -sTCP:LISTEN) 2>/dev/null
```

## Guardián (blindaje anti-regresiones)

`scripts/guardian.py` corta en el push las clases de bug que ya nos mordieron:
`.limit(N>1000)` en lecturas de Supabase (PostgREST corta en 1.000) y
`fromisoformat` directo (revienta en Railway/Py 3.10 con la fracción que
Postgres recorta → usar `backend.core.fechas.parse_iso_utc`). Revisa SOLO el
diff contra main, así que frena lo nuevo sin trabarse con lo viejo.

- Corre solo en cada push (GitHub Actions `.github/workflows/guardian.yml`).
- Hook local: `git config core.hooksPath .githooks` (una vez por clon).
- Ver la deuda vieja: `python3 scripts/guardian.py --full` (informativo).
- Excepción justificada: `# guardian: ok` al final de la línea.
