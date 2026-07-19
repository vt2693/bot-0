#!/data/data/com.termux/files/usr/bin/bash
# NOTE: no set -e — pkg mirrors are flaky; we handle failures explicitly

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Install system pkgs (mirrors flaky — don't abort on transient errors)
echo "Updating package lists..."
pkg update -y 2>&1 || echo "  ⚠ pkg update failed (mirror issue), trying to install directly..."

pkg install -y python ffmpeg tmux termux-api git binutils python-pip 2>&1 || echo "  ⚠ some pkg installs failed — continuing if core pkgs exist"

# Ensure storage access for /sdcard/Download
termux-setup-storage 2>/dev/null || echo "Storage already granted or run manually: termux-setup-storage"

# Clone or pull
if [ -f "$SCRIPT_DIR/android_bot.py" ]; then
  echo "Using local files at $SCRIPT_DIR"
  cd "$SCRIPT_DIR"
  git pull origin main 2>/dev/null || echo "git pull skipped, using local files"
else
  echo "Cloning repo..."
  cd /data/data/com.termux/files/home
  rm -rf hermes-bot 2>/dev/null
  echo "WARNING: vt2693/bot-0 remote repo not reachable. Use rsync/scp to copy the repo."
  echo "From your computer: rsync -avz bot-0/ termux@phone:~/hermes-bot/"
  echo "Or manually copy the files to ~/hermes-bot/ and re-run setup."
  mkdir -p hermes-bot
  cd hermes-bot
fi

# Install Python deps — bot now uses httpx directly, no openai SDK needed
echo "Installing numpy via pkg (pre-built)..."
pkg install -y python-numpy 2>/dev/null || true

# Ensure pip is up to date
pip install --upgrade pip 2>&1 | tail -1

echo "Installing Python packages (httpx only — no openai SDK)..."
pip install httpx 2>&1 || pip install --default-timeout=300 httpx 2>&1

# Verify critical imports
echo "Verifying packages..."
python -c "
import sys, importlib.util
pkgs = ['httpx', 'numpy']
missing = [p for p in pkgs if importlib.util.find_spec(p) is None]
if missing:
    print('ERROR: missing packages:', ' '.join(missing))
    sys.exit(1)
print('  ✓ all packages installed')
"

# Prompt for tokens
echo ""
echo "=== Hermes Bot Tokens ==="
echo "(press Enter to keep existing value)"
echo ""

# Load existing values
ENV_FILE="$HOME/.hermes-tokens.env"
EXISTING_TG=""
EXISTING_ROUTER=""; EXISTING_ROUTER_URL=""; EXISTING_ROUTER_AUDIO=""; EXISTING_COMPOSIO=""; EXISTING_OPENCODE=""

EXISTING_ALLOWED=""; EXISTING_EPICS=""
if [ -f "$ENV_FILE" ]; then
  . "$ENV_FILE"
  EXISTING_TG="$TELEGRAM_BOT_TOKEN"
  EXISTING_ROUTER="$ROUTER_0_API_KEY"
  EXISTING_ROUTER_URL="$ROUTER_0_BASE_URL"
  EXISTING_ROUTER_AUDIO="$ROUTER_0_AUDIO_URL"
  EXISTING_COMPOSIO="$COMPOSIO_CONSUMER_API_KEY"
  EXISTING_OPENCODE="$OPENCODE_ZEN_API_KEY"
  EXISTING_ALLOWED="$TELEGRAM_ALLOWED_USERS"
  EXISTING_EPICS="$JIRA_EPICS"
fi

read -p "TELEGRAM_BOT_TOKEN [${EXISTING_TG:-}]: " input
TELEGRAM_BOT_TOKEN="${input:-$EXISTING_TG}"

read -p "ROUTER_0_API_KEY [${EXISTING_ROUTER:-}]: " input
ROUTER_0_API_KEY="${input:-$EXISTING_ROUTER}"

read -p "ROUTER_0_BASE_URL [${EXISTING_ROUTER_URL:-}]: " input
ROUTER_0_BASE_URL="${input:-$EXISTING_ROUTER_URL}"

read -p "ROUTER_0_AUDIO_URL (TTS/STT) [${EXISTING_ROUTER_AUDIO:-}]: " input
ROUTER_0_AUDIO_URL="${input:-${EXISTING_ROUTER_AUDIO:-http://192.168.1.6:20128/v1}}"

read -p "COMPOSIO_CONSUMER_API_KEY [${EXISTING_COMPOSIO:-}]: " input
COMPOSIO_CONSUMER_API_KEY="${input:-$EXISTING_COMPOSIO}"

read -p "OPENCODE_ZEN_API_KEY [${EXISTING_OPENCODE:-}]: " input
OPENCODE_ZEN_API_KEY="${input:-$EXISTING_OPENCODE}"

read -p "TELEGRAM_ALLOWED_USERS (comma-separated IDs, optional) [${EXISTING_ALLOWED:-}]: " input
TELEGRAM_ALLOWED_USERS="${input:-$EXISTING_ALLOWED}"

read -p "JIRA_EPICS (comma-separated, optional) [${EXISTING_EPICS:-}]: " input
JIRA_EPICS="${input:-$EXISTING_EPICS}"

cat > "$ENV_FILE" <<EOF
export TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN}"
export ROUTER_0_API_KEY="${ROUTER_0_API_KEY}"
export ROUTER_0_BASE_URL="${ROUTER_0_BASE_URL}"
export ROUTER_0_AUDIO_URL="${ROUTER_0_AUDIO_URL}"
export COMPOSIO_CONSUMER_API_KEY="${COMPOSIO_CONSUMER_API_KEY}"
export OPENCODE_ZEN_API_KEY="${OPENCODE_ZEN_API_KEY}"
export TELEGRAM_ALLOWED_USERS="${TELEGRAM_ALLOWED_USERS}"
export PROVIDER="router_0"
export BROADCAST_CHAT_ID=""
export JIRA_EPICS="${JIRA_EPICS}"
# Leave HF_TOKEN env var unset to prevent memory_store.py from attempting
# backup to a deleted remote repo. MEMORY_SPACE_ID is set to "none"
# so the backup guard ("/" in path) skips.
export MEMORY_SPACE_ID="none"
EOF
chmod 600 "$ENV_FILE"
echo "Saved $ENV_FILE"

echo ""
echo "Done. Run: bash start_android.sh"
