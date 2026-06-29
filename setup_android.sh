#!/data/data/com.termux/files/usr/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Install deps
pkg update -y
pkg install -y python ffmpeg tmux termux-api git

# Repo: git pull if exists, clone if not
if [ -f "$SCRIPT_DIR/relay.py" ]; then
  echo "Repo already cloned at $SCRIPT_DIR"
  cd "$SCRIPT_DIR"
  git pull origin main 2>/dev/null || echo "git pull failed (no upstream?), using local files"
else
  echo "Cloning repo..."
  cd /data/data/com.termux/files/home
  rm -rf hermes-relay 2>/dev/null
  git clone https://huggingface.co/spaces/vt2693/bot-0 hermes-relay
  cd hermes-relay
fi

# Prompt for tokens (always runs)
echo ""
echo "=== Hermes Relay Tokens ==="
echo "(press Enter to keep existing value, or skip if blank)"
echo ""

# Hardcoded defaults (script values always win over stale env file)
DEFAULT_SPACE_URL="https://vt2693-bot-0.hf.space"
DEFAULT_WORK_DIR="/sdcard/Download"
DEFAULT_POLL="3"

# Load existing values only for previously-entered secrets
EXISTING_TG=""; EXISTING_GROQ=""; EXISTING_NVIDIA=""
if [ -f "$HOME/.hermes-tokens.env" ]; then
  . "$HOME/.hermes-tokens.env"
  EXISTING_TG="$TELEGRAM_BOT_TOKEN"
  EXISTING_GROQ="$GROQ_API_KEY"
  EXISTING_NVIDIA="$NVIDIA_API_KEY"
fi

read -p "SPACE_URL [$DEFAULT_SPACE_URL]: " input
SPACE_URL="${input:-$DEFAULT_SPACE_URL}"

read -p "TELEGRAM_BOT_TOKEN [${EXISTING_TG:-}]: " input
TELEGRAM_BOT_TOKEN="${input:-$EXISTING_TG}"

BOT_TOKEN="$TELEGRAM_BOT_TOKEN"

read -p "GROQ_API_KEY [${EXISTING_GROQ:-}]: " input
GROQ_API_KEY="${input:-$EXISTING_GROQ}"

read -p "NVIDIA_API_KEY [${EXISTING_NVIDIA:-}]: " input
NVIDIA_API_KEY="${input:-$EXISTING_NVIDIA}"

cat > "$HOME/.hermes-tokens.env" <<EOF
export SPACE_URL="${SPACE_URL}"
export TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN}"
export BOT_TOKEN="\${TELEGRAM_BOT_TOKEN}"
export GROQ_API_KEY="${GROQ_API_KEY}"
export NVIDIA_API_KEY="${NVIDIA_API_KEY}"
export WORK_DIR="/sdcard/Download"
export POLL_INTERVAL="1"
EOF
chmod 600 "$HOME/.hermes-tokens.env"
echo "Saved $HOME/.hermes-tokens.env"

echo ""
echo "Done. Run: bash start_android.sh"
