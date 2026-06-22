#!/data/data/com.termux/files/usr/bin/bash
set -e
pkg update -y
pkg install -y python ffmpeg tmux termux-api git
python -m pip install --upgrade pip
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
echo "Created $HOME/.hermes-tokens.env. Edit it, then run: bash start_android.sh"
