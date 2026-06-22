#!/data/data/com.termux/files/usr/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Install deps
pkg update -y
pkg install -y python ffmpeg tmux termux-api git
python -m pip install --upgrade pip

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

# Tokens file (only create if missing)
if [ ! -f "$HOME/.hermes-tokens.env" ]; then
  cat > "$HOME/.hermes-tokens.env" <<'EOF'
# Fill values, then run: bash start_android.sh
export SPACE_URL="https://vt2693-bot-0.hf.space"
export TELEGRAM_BOT_TOKEN=""
export BOT_TOKEN="$TELEGRAM_BOT_TOKEN"
export GROQ_API_KEY=""
export NVIDIA_API_KEY=""
export WORK_DIR="/sdcard/Download"
export POLL_INTERVAL="3"
EOF
  chmod 600 "$HOME/.hermes-tokens.env"
  echo "Created $HOME/.hermes-tokens.env — EDIT IT with your tokens."
else
  echo "$HOME/.hermes-tokens.env exists — keeping it."
fi

echo "Done. cd ~/hermes-relay && nano ~/.hermes-tokens.env && bash start_android.sh"
