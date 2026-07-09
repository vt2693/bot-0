#!/data/data/com.termux/files/usr/bin/bash
cd "$(dirname "$0")" || cd ~/hermes-bot

ENV_FILE="$HOME/.hermes-tokens.env"
if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE. Run: setup_android.sh"
  exit 1
fi
. "$ENV_FILE"

export PATH=/data/data/com.termux/files/usr/bin:$PATH
export TEMP_DIR="${TEMP_DIR:-$HOME/.cache/hermes-tmp}"
export WORK_DIR="${WORK_DIR:-/sdcard/Download}"
mkdir -p "$TEMP_DIR" logs

termux-wake-lock || true
tmux kill-session -t hermes 2>/dev/null || true
tmux new-session -d -s hermes -n bot \
  "while true; do python -u android_bot.py 2>&1 | tee -a logs/bot.log; echo 'Bot crashed, restarting in 2s...'; sleep 2; done"

echo "Hermes bot started. Attach: tmux attach -t hermes"
