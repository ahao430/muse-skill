#!/usr/bin/env bash
# muse-skill first-run setup wizard.
# Guides you through: dependencies → SDK token → pairing → MCP registration.
# Safe to re-run: every step skips what is already done.

set -euo pipefail
cd "$(dirname "$0")/.."

BLUE='\033[1;34m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
step() { printf "${BLUE}==> %s${NC}\n" "$*"; }
ok()   { printf "${GREEN}  ✓ %s${NC}\n" "$*"; }
todo() { printf "${YELLOW}  → %s${NC}\n" "$*"; }

RUNNER=""; for r in bun node; do command -v "$r" >/dev/null 2>&1 && RUNNER="$r" && break; done

echo
echo "  Muse Agent Skill — setup"
echo "  Route A (local, Mac Bluetooth) is the default; Route B (ssh, Linux"
echo "  gadget host) can be added later, see docs/pairing.md."
echo

# 1. Python deps
step "1/5 Python dependencies"
if [[ -d .venv ]]; then ok "venv present"; else
  todo "run: uv sync"; echo "uv sync"; fi
uv sync --quiet 2>/dev/null && ok "uv sync done"

# 2. bridge deps
step "2/5 Bridge dependencies (muse-client)"
if [[ -d bridge/node_modules/muse-client ]]; then ok "muse-client installed"; else
  if [[ -n "$RUNNER" ]]; then (cd bridge && "$RUNNER" install) && ok "installed with $RUNNER"
  else todo "install bun first: curl -fsSL https://bun.sh/install | bash"; fi
fi

# 3. SDK token
step "3/5 SDK token"
TOKEN_FILE="$HOME/.config/muse-agent/sdk_token"
if [[ -s "$TOKEN_FILE" ]] && head -c 5 "$TOKEN_FILE" | grep -q mgst_; then
  ok "token saved at $TOKEN_FILE"
else
  todo "get a token at https://gadgets.muse.ai/settings/sdk-tokens then:"
  printf "  mkdir -p ~/.config/muse-agent\n  read -s TOKEN && echo \"\$TOKEN\" > %s && chmod 600 %s\n" "$TOKEN_FILE" "$TOKEN_FILE"
  read -rp "  paste token now (Enter to skip): " T
  if [[ -n "$T" ]]; then mkdir -p ~/.config/muse-agent; printf '%s' "$T" > "$TOKEN_FILE"; chmod 600 "$TOKEN_FILE"; ok "token saved"; fi
fi

# 4. pairing
step "4/5 Pairing (one-time, Mac Bluetooth)"
CREDS="$HOME/Library/Application Support/MuseGadgetPair"
if [[ -f "$CREDS/pairing.json" || -f "$CREDS/credentials.json" ]]; then
  ok "already paired ($CREDS)"
else
  todo "run: $RUNNER bridge/bridge.mjs pair   (then confirm on your phone)"
  if [[ -s "$TOKEN_FILE" && -n "$RUNNER" ]] && read -rp "  start pairing now? [y/N] " A && [[ "$A" = y ]]; then
    MUSE_SDK_TOKEN="$(cat "$TOKEN_FILE")" "$RUNNER" bridge/bridge.mjs pair
  fi
fi

# 5. verify
step "5/5 Verify"
if [[ -n "$RUNNER" ]] && "$RUNNER" bridge/bridge.mjs status 2>/dev/null | grep -q '"ready": true'; then
  ok "Muse connection ready — register the MCP server next:"
  printf "  claude mcp add muse -- uv --directory %s run muse-agent\n" "$(pwd)"
  printf "  or copy .mcp.json into your client config (docs/zcode.md)\n"
else
  todo "not ready yet — run: uv run muse-agent --status  or  uv run muse_doctor via your agent"
fi
echo
