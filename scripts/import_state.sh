#!/usr/bin/env bash
# Import musegadget pairing state from a pairing machine into the gadget host.
#
# After the one-time BLE pairing (docs/pairing.md), the pairing machine holds:
#   /var/lib/musegadget/identity.json   device identity
#   /var/lib/musegadget/pairing.json    device tokens
# This script copies them to the always-on gadget host so the musegadget
# service there connects to Muse as the same device.
#
# Usage (run on the Mac):
#   scripts/import_state.sh <pairing-state-dir> [--host USER@HOST]
#
# <pairing-state-dir>  local directory containing identity.json + pairing.json
#                      (scp them off the pairing machine first)

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <pairing-state-dir> [--host USER@HOST]" >&2
  exit 2
fi

STATE_DIR="$1"; shift || true
HOST="${MUSE_AGENT_HOST:-}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$HOST" ]]; then
  echo "No host. Pass --host USER@HOST or set MUSE_AGENT_HOST." >&2
  exit 2
fi

for f in identity.json pairing.json; do
  if [[ ! -f "$STATE_DIR/$f" ]]; then
    echo "missing $STATE_DIR/$f — copy it from the pairing machine's /var/lib/musegadget/" >&2
    exit 1
  fi
done

echo "==> copying pairing state to $HOST"
scp -o BatchMode=yes "$STATE_DIR/identity.json" "$STATE_DIR/pairing.json" "$HOST:/tmp/"

ssh -o BatchMode=yes "$HOST" '
set -e
install -d -m 0700 /var/lib/musegadget
install -m 0600 /tmp/identity.json /tmp/pairing.json /var/lib/musegadget/
rm -f /tmp/identity.json /tmp/pairing.json
systemctl restart musegadget
sleep 3
systemctl is-active musegadget
musegadget info
'
echo "==> done. Verify with: uv run muse-agent --status"
