#!/usr/bin/env bash
# Start the HandOver server in one process:
#   http  on 0.0.0.0:8000 (laptop UI through the Vite proxy, replay script, glasses app)
#   https on 0.0.0.0:8443 when certs/cert.pem and certs/key.pem exist (the iPhone camera page needs HTTPS)
# Both ports share one learn session. Create certs with scripts/certs.sh. Ctrl+C stops the server.
# Env passes through, for example: HANDOVER_CHECK=mock scripts/run_server.sh
# Ports can be changed with HANDOVER_PORT and HANDOVER_HTTPS_PORT.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ -f certs/cert.pem ] && [ -f certs/key.pem ]; then
  IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)"
  echo "Phone camera page: https://${IP:-<laptop IP>}:${HANDOVER_HTTPS_PORT:-8443}/capture"
fi
exec "$ROOT/.venv/bin/python" -m server.main
