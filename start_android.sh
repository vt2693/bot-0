#!/data/data/com.termux/files/usr/bin/bash
cd "$(dirname "$0")" || cd ~/hermes-relay

ENV_FILE="$HOME/.hermes-tokens.env"
if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE. Run: setup_android.sh"
  exit 1
fi
. "$ENV_FILE"

export PATH=/data/data/com.termux/files/usr/bin:$PATH
export SPACE_URL="${SPACE_URL:-https://vt2693-bot-0.hf.space}"
export BOT_TOKEN="${BOT_TOKEN:-$TELEGRAM_BOT_TOKEN}"
export TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-$BOT_TOKEN}"
export TEMP_DIR="${TEMP_DIR:-$HOME/.cache/hermes-tmp}"
export WORK_DIR="${WORK_DIR:-/sdcard/Download}"
export POLL_INTERVAL="${POLL_INTERVAL:-1}"
mkdir -p "$TEMP_DIR" "$WORK_DIR" logs

termux-wake-lock || true
tmux kill-session -t hermes 2>/dev/null || true
tmux new-session -d -s hermes -n relay "while true; do python -u relay.py 2>&1 | tee -a logs/relay.log; echo 'Relay crashed, restarting in 2s...'; sleep 2; done"
tmux new-window -t hermes -n voice "while true; do python -u voice_relay.py 2>&1 | tee -a logs/voice.log; echo 'Voice relay crashed, restarting in 2s...'; sleep 2; done"
echo "Hermes relays started. Attach: tmux attach -t hermes"
