#!/usr/bin/env bash
# Provision the remote gadget host: install the musegadget SDK and service.
#
# Usage:
#   scripts/provision.sh [--host USER@HOST] [--sdk-token mgst_…] [--dry-run]
#
# --host      overrides ~/.config/muse-agent/config.yaml / MUSE_AGENT_HOST
# --sdk-token SDK token from gadgets.muse.ai (only needed on first install;
#             never stored on the Mac)
# --dry-run   print the remote commands instead of running them
#
# Pairing is NOT done here (it needs BLE). See docs/pairing.md.

set -euo pipefail

HOST="${MUSE_AGENT_HOST:-$(python3 - <<'EOF'
from pathlib import Path
p = Path.home() / ".config/muse-agent/config.yaml"
if p.exists():
    for line in p.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line.startswith("host:"):
            print(line.split(":", 1)[1].strip().strip("'\""))
            break
EOF
)}"
SDK_TOKEN=""
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --sdk-token) SDK_TOKEN="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$HOST" ]]; then
  echo "No host. Pass --host USER@HOST or set MUSE_AGENT_HOST." >&2
  exit 2
fi

SSH_CMD=(ssh -o BatchMode=yes -o ConnectTimeout=10 "$HOST")

# Everything below runs on the remote host.
REMOTE_SCRIPT=$(cat <<'REMOTE'
set -euo pipefail

need() { command -v "$1" >/dev/null 2>&1 || { echo "missing: $1" >&2; MISSING=1; }; }
MISSING=0
need curl; need python3; need git
[[ $MISSING -eq 1 ]] && { echo "install curl/python3/git first (apt install -y curl python3 git)" >&2; exit 1; }

if [[ ! -d /opt/musegadget ]]; then
  echo "==> downloading install.sh"
  curl -fsSL -o /tmp/musegadget-install.sh \
    https://raw.githubusercontent.com/facebookincubator/muse-gadget-sdk/main/linux/install.sh
  chmod +x /tmp/musegadget-install.sh
  TOKEN_ARGS=()
  [[ -n "${MUSE_SDK_TOKEN:-}" ]] && TOKEN_ARGS=(--sdk-token "$MUSE_SDK_TOKEN")
  echo "==> running install.sh ${TOKEN_ARGS[*]:0:1} ***"
  bash /tmp/musegadget-install.sh --yes "${TOKEN_ARGS[@]}"
else
  echo "==> /opt/musegadget already installed"
fi

echo "==> service status"
systemctl is-active musegadget || true
musegadget info || true
REMOTE
)

if [[ $DRY_RUN -eq 1 ]]; then
  echo "# would run on $HOST:"
  echo "$REMOTE_SCRIPT"
  exit 0
fi

# Pass the token through the remote environment without echoing it.
if [[ -n "$SDK_TOKEN" ]]; then
  "${SSH_CMD[@]}" "MUSE_SDK_TOKEN='$SDK_TOKEN' bash -s" <<< "$REMOTE_SCRIPT"
else
  "${SSH_CMD[@]}" "bash -s" <<< "$REMOTE_SCRIPT"
fi
