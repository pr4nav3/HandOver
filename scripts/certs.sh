#!/usr/bin/env bash
# Make HTTPS certificates so iPhone Safari can open the camera page (getUserMedia needs HTTPS).
# Writes certs/cert.pem and certs/key.pem for the laptop's LAN or hotspot IP, localhost and 127.0.0.1.
# Uses mkcert. This script installs nothing except, with your OK, the mkcert local root on this Mac.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v mkcert >/dev/null 2>&1; then
  echo "mkcert is not installed. Install it with:"
  echo "  brew install mkcert"
  echo "then run scripts/certs.sh again."
  exit 1
fi

IP=""
for ifc in en0 en1 en2 bridge100; do
  IP="$(ipconfig getifaddr "$ifc" 2>/dev/null || true)"
  [ -n "$IP" ] && break
done
if [ -z "$IP" ]; then
  IP="$(ifconfig | awk '/inet / && $2 != "127.0.0.1" {print $2; exit}')"
fi
if [ -z "$IP" ]; then
  echo "Could not find a network IP. Join Wi-Fi or the phone's hotspot, then run this again."
  exit 1
fi
echo "Laptop IP: $IP"

CAROOT="$(mkcert -CAROOT)"
if [ ! -f "$CAROOT/rootCA.pem" ] || ! security find-certificate -c "mkcert" >/dev/null 2>&1; then
  echo
  echo "mkcert will now create a local certificate authority (a private root certificate) in:"
  echo "  $CAROOT"
  echo "and add it to this Mac's trust store, so the browser here trusts the certificates it issues."
  echo "macOS may ask for your password. The root key never leaves this Mac."
  read -r -p "Continue? [y/N] " ok
  case "$ok" in y|Y|yes) ;; *) echo "Stopped. Nothing changed."; exit 1 ;; esac
  mkcert -install
fi

mkdir -p certs
mkcert -cert-file certs/cert.pem -key-file certs/key.pem "$IP" localhost 127.0.0.1

cat <<MSG

Done: certs/cert.pem and certs/key.pem (certs/ is gitignored).

Trust the root on the iPhone, once:
  1. AirDrop this file to the iPhone:  $CAROOT/rootCA.pem
     (open -R "$CAROOT/rootCA.pem" shows it in Finder)
  2. On the iPhone, tap Allow, then Settings > Profile Downloaded > Install.
  3. Settings > General > About > Certificate Trust Settings: turn on the mkcert root.

Then start the server (scripts/run_server.sh) and open on the iPhone:
  https://$IP:8443/capture

The phone and laptop must be on the same network (or the laptop on the phone's hotspot).
If the IP changes, run this script again.

Fallback if certificates are a hassle: a Cloudflare quick tunnel gives a public HTTPS URL with no setup:
  brew install cloudflared
  cloudflared tunnel --url http://localhost:8000
Then open https://<random>.trycloudflare.com/capture on the iPhone. Frames go through Cloudflare, so it adds latency.
MSG
