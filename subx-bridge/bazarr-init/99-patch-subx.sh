#!/usr/bin/with-contenv bash
# Make Bazarr's bundled SubX provider point at our local subx-bridge.
# The provider hardcodes _SUBX_BASE_URL; this rewrites it to read the
# SUBX_BASE_URL env var (set on the bazarr service). Runs on every start,
# so it re-applies after image updates. Idempotent.
set -e

SUBX_FILE="/app/bazarr/bin/custom_libs/subliminal_patch/providers/subx.py"

if [ ! -f "$SUBX_FILE" ]; then
    echo "[subx-patch] $SUBX_FILE not found; skipping"
    exit 0
fi

if grep -q '^_SUBX_BASE_URL = "https://subx-api.duckdns.org"$' "$SUBX_FILE"; then
    sed -i 's#^_SUBX_BASE_URL = "https://subx-api.duckdns.org"$#_SUBX_BASE_URL = os.environ.get("SUBX_BASE_URL", "https://subx-api.duckdns.org")#' "$SUBX_FILE"
    echo "[subx-patch] Patched subx.py to honor SUBX_BASE_URL (=${SUBX_BASE_URL:-<unset>})"
else
    echo "[subx-patch] subx.py already patched or upstream changed; skipping"
fi
