# SubX Bridge for Bazarr

Bridge compatible con el provider `SubX` de Bazarr, implementado sobre el flujo directo de Subdivx.

Se puede ejecutar localmente con Python/uvicorn o desplegar en Docker. En la práctica, la opción más cómoda suele ser correrlo en Docker junto con Jellyfin, Bazarr y el resto del stack *arr.

## 🧩 Por qué existe este bridge

El provider `SubX` de Bazarr fue pensado para trabajar contra una API externa de SubX.

En la práctica, esa API ya no está funcionando de forma confiable o directamente dejó de estar disponible, así que este proyecto nace como reemplazo compatible para seguir usando SubX/Subdivx desde Bazarr.

La idea del bridge es:

- mantener una interfaz simple y utilizable desde Bazarr
- evitar depender de una API pública caída o abandonada
- hablar directo con Subdivx usando cookies y headers controlados por el usuario
- dejar la integración bajo tu propio control

## ✨ Qué resuelve

- expone `GET /api/subtitles/search`
- expone `GET /api/subtitles/{id}/download`
- usa autenticación Bearer como espera Bazarr
- busca en Subdivx usando cookies manuales (`cf_clearance` + `sdx`) o `Cookie` completa
- prioriza `tmdb_id` para resolver título/año cuando Bazarr no envía `title`
- usa `imdb_id` como fallback cuando TMDb no alcanza o no está configurado

## ⚙️ Variables de entorno

- `SUBX_API_KEYS`: API keys permitidas, separadas por coma. Son claves arbitrarias definidas por vos para proteger el bridge; no las entrega Subdivx ni Bazarr.
- `SUBDIVX_COOKIE_HEADER`: header `Cookie` completo, opcional
- `SUBDIVX_CF_CLEARANCE`: valor de `cf_clearance`, opcional si usás `SUBDIVX_COOKIE_HEADER`
- `SUBDIVX_SDX`: valor de `sdx`, opcional si usás `SUBDIVX_COOKIE_HEADER`
- `SUBDIVX_USER_AGENT`: user-agent a reutilizar con las cookies
- `SUBDIVX_BASE_URL`: default `https://subdivx.com`
- `IMDB_BASE_URL`: default `https://www.imdb.com`
- `TMDB_BASE_URL`: default `https://api.themoviedb.org/3`
- `TMDB_API_KEY`: API key v3 de TMDb, opcional
- `TMDB_READ_ACCESS_TOKEN`: read access token de TMDb, opcional
- `LOG_LEVEL`: default `INFO`

## 🚀 Ejecutar

```bash
cd /ruta/a/subx-bridge
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export SUBX_API_KEYS="change-me-api-key"
export SUBDIVX_CF_CLEARANCE="..."
export SUBDIVX_SDX="..."
export SUBDIVX_USER_AGENT="Mozilla/5.0 (X11; Linux x86_64; rv:148.0) Gecko/20100101 Firefox/148.0"
export TMDB_READ_ACCESS_TOKEN="..."

uvicorn subx_bridge.main:app --host 0.0.0.0 --port 8787
```

`change-me-api-key` es solo un placeholder de ejemplo: reemplázalo por cualquier valor secreto propio y luego usa ese mismo valor en Bazarr.

## 🐳 Ejecutar con Docker

```bash
cd /ruta/a/subx-bridge
docker compose up -d --build
```

Prueba rápida:

```bash
curl http://127.0.0.1:8787/health
```

## 🧪 Probar la API sola

Smoke test básico:

```bash
curl http://127.0.0.1:8787/health
curl -i "http://127.0.0.1:8787/api/subtitles/search?video_type=movie&title=Relatos%20salvajes" \
  -H "Authorization: Bearer change-me-api-key"
```

Probe de búsqueda:

```bash
cd /ruta/a/subx-bridge
python3 tools/bridge_probe.py \
  --base-url http://127.0.0.1:8787 \
  --api-key change-me-api-key \
  --video-type movie \
  --title "Relatos salvajes" \
  --year 2014
```

Probe de episodio usando IMDb y probando descarga del primer resultado:

```bash
cd /ruta/a/subx-bridge
python3 tools/bridge_probe.py \
  --base-url http://127.0.0.1:8787 \
  --api-key change-me-api-key \
  --video-type episode \
  --imdb-id tt0386676 \
  --download-first
```

Checklist mínima antes de integrar en Jellyfin:

- `GET /health` responde `200`
- sin `Authorization` devuelve `401`
- con bearer válido devuelve resultados en `GET /api/subtitles/search`
- `title + year` encuentra películas razonables
- `tmdb_id` resuelve bien título/año cuando no mandas `title`
- `imdb_id` queda como fallback secundario
- `GET /api/subtitles/{id}/download` devuelve bytes y `Content-Type`
- Subdivx no devuelve `429` con la cadencia actual

## 🔌 Configurar Bazarr

En el provider `SubX`:

- API key: una de `SUBX_API_KEYS`

La API key acá no viene de Subdivx. Es simplemente una clave tuya, definida en el bridge, para que Bazarr pueda autenticarse contra tu instancia.

El provider actual de Bazarr tiene la URL base hardcodeada a `https://subx-api.duckdns.org`, así que tienes tres opciones:

1. Parchear `custom_libs/subliminal_patch/providers/subx.py` y cambiar `_SUBX_BASE_URL`.
2. Publicar tu bridge detrás de un reverse proxy y hacer que Bazarr resuelva ese hostname a tu bridge.
3. Montar un override local del archivo `subx.py`.

El parche mínimo es este:

```python
_SUBX_BASE_URL = "http://TU_HOST_O_IP:8787"
```

Mejor todavía, déjalo configurable por entorno:

```python
_SUBX_BASE_URL = os.environ.get("SUBX_BASE_URL", "https://subx-api.duckdns.org")
```

Archivo:

```text
custom_libs/subliminal_patch/providers/subx.py
```

Y en el contenedor de Bazarr:

```bash
SUBX_BASE_URL=http://subx-bridge:8787
```

## 📝 Notas

- El endpoint de descarga devuelve el archivo comprimido original de Subdivx; Bazarr se encarga de extraer el subtítulo.
- Si Bazarr manda `tmdb_id`, el bridge intenta resolver título/año desde TMDb antes de buscar en Subdivx.
- Si no hay TMDb disponible, el bridge usa IMDb como fallback secundario.
- Cloudflare puede invalidar la sesión o incluso bloquear temporalmente la IP.
- Si se rompe la sesión, normalmente alcanza con renovar `SUBDIVX_COOKIE_HEADER` o volver a cargar `cf_clearance` + `sdx`.
- Si el problema es la IP, a veces no queda otra que esperar unas horas hasta que Subdivx/Cloudflare vuelva a aceptar cookies útiles desde esa conexión.
- La forma más simple de comprobarlo es probar manualmente en la web: si con esas cookies el sitio no devuelve resultados en el navegador, el bridge tampoco va a poder encontrarlos.
