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
  echo "WARNING: vt2693/bot-0 HF Space is deleted. Use rsync/scp to copy the repo."
  echo "From your computer: rsync -avz bot-0/ termux@phone:~/hermes-bot/"
  echo "Or manually copy the files to ~/hermes-bot/ and re-run setup."
  mkdir -p hermes-bot
  cd hermes-bot
fi

# Install Python deps (minimal — no FastAPI/Gradio)
# Python 3.14 on Termux: jiter (openai dep, C/Rust) has no 3.14 wheel
# and aarch64-unknown-linux-android isn't known to rustup. Install
# jiter via pkg (pre-built), rest via pip.
echo "Installing pre-built C-extension deps via pkg..."
pkg install -y python-numpy python-jiter 2>/dev/null || true

# Ensure pip is up to date
pip install --upgrade pip 2>&1 | tail -1

echo "Installing Python packages..."
pip install openai httpx 2>&1 || pip install --default-timeout=300 openai httpx 2>&1

# Verify critical imports
echo "Verifying packages..."
python -c "
import sys, importlib.util
pkgs = ['openai', 'httpx', 'numpy']
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
EXISTING_TG=""; EXISTING_GROQ=""; EXISTING_NVIDIA=""
EXISTING_ROUTER=""; EXISTING_COMPOSIO=""; EXISTING_OPENCODE=""
EXISTING_GOOGLE=""; EXISTING_ANTHROPIC=""; EXISTING_OPENAI=""
if [ -f "$ENV_FILE" ]; then
  . "$ENV_FILE"
  EXISTING_TG="$TELEGRAM_BOT_TOKEN"
  EXISTING_GROQ="$GROQ_API_KEY"
  EXISTING_NVIDIA="$NVIDIA_API_KEY"
  EXISTING_ROUTER="$ROUTER_0_API_KEY"
  EXISTING_COMPOSIO="$COMPOSIO_CONSUMER_API_KEY"
  EXISTING_OPENCODE="$OPENCODE_ZEN_API_KEY"
  EXISTING_GOOGLE="$GOOGLE_API_KEY"
  EXISTING_ANTHROPIC="$ANTHROPIC_API_KEY"
  EXISTING_OPENAI="$OPENAI_API_KEY"
fi

read -p "TELEGRAM_BOT_TOKEN [${EXISTING_TG:-}]: " input
TELEGRAM_BOT_TOKEN="${input:-$EXISTING_TG}"

read -p "GROQ_API_KEY [${EXISTING_GROQ:-}]: " input
GROQ_API_KEY="${input:-$EXISTING_GROQ}"

read -p "NVIDIA_API_KEY [${EXISTING_NVIDIA:-}]: " input
NVIDIA_API_KEY="${input:-$EXISTING_NVIDIA}"

read -p "ROUTER_0_API_KEY [${EXISTING_ROUTER:-}]: " input
ROUTER_0_API_KEY="${input:-$EXISTING_ROUTER}"

read -p "COMPOSIO_CONSUMER_API_KEY [${EXISTING_COMPOSIO:-}]: " input
COMPOSIO_CONSUMER_API_KEY="${input:-$EXISTING_COMPOSIO}"

read -p "OPENCODE_ZEN_API_KEY [${EXISTING_OPENCODE:-}]: " input
OPENCODE_ZEN_API_KEY="${input:-$EXISTING_OPENCODE}"

read -p "GOOGLE_API_KEY [${EXISTING_GOOGLE:-}]: " input
GOOGLE_API_KEY="${input:-$EXISTING_GOOGLE}"

read -p "ANTHROPIC_API_KEY [${EXISTING_ANTHROPIC:-}]: " input
ANTHROPIC_API_KEY="${input:-$EXISTING_ANTHROPIC}"

read -p "OPENAI_API_KEY [${EXISTING_OPENAI:-}]: " input
OPENAI_API_KEY="${input:-$EXISTING_OPENAI}"

cat > "$ENV_FILE" <<EOF
export TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN}"
export GROQ_API_KEY="${GROQ_API_KEY}"
export NVIDIA_API_KEY="${NVIDIA_API_KEY}"
export ROUTER_0_API_KEY="${ROUTER_0_API_KEY}"
export COMPOSIO_CONSUMER_API_KEY="${COMPOSIO_CONSUMER_API_KEY}"
export OPENCODE_ZEN_API_KEY="${OPENCODE_ZEN_API_KEY}"
export GOOGLE_API_KEY="${GOOGLE_API_KEY}"
export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}"
export OPENAI_API_KEY="${OPENAI_API_KEY}"
export PROVIDER="router_0"
export BROADCAST_CHAT_ID=""
# Leave HF_TOKEN unset to prevent memory_store.py from attempting
# backup to deleted Space (vt2693/bot-0). MEMORY_SPACE_ID is set
# to an invalid Space name so the backup guard ("/" in path) skips.
export MEMORY_SPACE_ID="none"
EOF
chmod 600 "$ENV_FILE"
echo "Saved $ENV_FILE"

echo ""
echo "Done. Run: bash start_android.sh"
