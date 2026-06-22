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

# Load existing values if any
if [ -f "$HOME/.hermes-tokens.env" ]; then
  . "$HOME/.hermes-tokens.env"
fi

read -p "SPACE_URL [${SPACE_URL:-https://vt2693-bot-0.hf.space}]: " input
SPACE_URL="${input:-${SPACE_URL:-https://vt2693-bot-0.hf.space}}"

read -p "TELEGRAM_BOT_TOKEN [${TELEGRAM_BOT_TOKEN:-}]: " input
TELEGRAM_BOT_TOKEN="${input:-$TELEGRAM_BOT_TOKEN}"

BOT_TOKEN="$TELEGRAM_BOT_TOKEN"

read -p "GROQ_API_KEY [${GROQ_API_KEY:-}]: " input
GROQ_API_KEY="${input:-$GROQ_API_KEY}"

read -p "NVIDIA_API_KEY [${NVIDIA_API_KEY:-}]: " input
NVIDIA_API_KEY="${input:-$NVIDIA_API_KEY}"

cat > "$HOME/.hermes-tokens.env" <<EOF
export SPACE_URL="${SPACE_URL}"
export TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN}"
export BOT_TOKEN="\${TELEGRAM_BOT_TOKEN}"
export GROQ_API_KEY="${GROQ_API_KEY}"
export NVIDIA_API_KEY="${NVIDIA_API_KEY}"
export WORK_DIR="/sdcard/Download"
export POLL_INTERVAL="3"
EOF
chmod 600 "$HOME/.hermes-tokens.env"
echo "Saved $HOME/.hermes-tokens.env"

echo ""
echo "Done. Run: bash start_android.sh"
