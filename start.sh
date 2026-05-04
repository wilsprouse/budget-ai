#!/usr/bin/env bash
# start.sh — convenience wrapper to start the budget-ai stack
#
# Usage:
#   ./start.sh                # start in foreground (logs visible)
#   ./start.sh -d             # start detached (background)
#   ./start.sh --model phi3:mini  # use a different model
#   ./start.sh --install-deps # install podman and podman-compose, then start
set -euo pipefail

MODEL="${DEFAULT_MODEL:-tinyllama}"
DETACH=""
SELECTED_MODEL="$MODEL"
INSTALL_DEPS=false

# ---------------------------------------------------------------------------
# install_deps — detect the OS and install podman + podman-compose
# ---------------------------------------------------------------------------
install_deps() {
  echo "Checking for podman and podman-compose..."

  local need_podman=false
  local need_compose=false

  podman --version &>/dev/null || need_podman=true
  podman-compose --version &>/dev/null || need_compose=true

  if [[ "$need_podman" == false && "$need_compose" == false ]]; then
    echo "podman and podman-compose are already installed — nothing to do."
    return
  fi

  if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS — requires Homebrew
    if ! command -v brew &>/dev/null; then
      echo "ERROR: Homebrew is required to install podman on macOS."
      echo "       Install it from https://brew.sh/ and re-run with --install-deps."
      exit 1
    fi
    [[ "$need_podman" == true ]]  && brew install podman
    [[ "$need_compose" == true ]] && brew install podman-compose
  elif grep -qiE '^(ID|ID_LIKE)=.*\b(ubuntu|debian)\b' /etc/os-release 2>/dev/null; then
    # Ubuntu / Debian (and derivatives that set ID_LIKE=ubuntu|debian)
    echo "Running apt-get update (this may take a moment)..."
    sudo apt-get update -qq
    [[ "$need_podman" == true ]]  && sudo apt-get install -y podman
    [[ "$need_compose" == true ]] && sudo apt-get install -y podman-compose
  elif grep -qiE '^(ID|ID_LIKE)=.*\b(fedora|rhel|centos|rocky|almalinux)\b' /etc/os-release 2>/dev/null; then
    # Fedora / RHEL / CentOS / Rocky / AlmaLinux (and derivatives)
    [[ "$need_podman" == true ]]  && sudo dnf install -y podman
    [[ "$need_compose" == true ]] && sudo dnf install -y podman-compose
  else
    local os_id=""
    os_id="$(grep '^ID=' /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '"' || echo "unknown")"
    echo "ERROR: Unsupported OS (detected: '${os_id}'). Please install podman manually:"
    echo "       https://podman.io/docs/installation"
    exit 1
  fi

  echo "Dependencies installed successfully."
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -d|--detach)
      DETACH="-d"
      shift
      ;;
    --model)
      SELECTED_MODEL="$2"
      shift 2
      ;;
    --install-deps)
      INSTALL_DEPS=true
      shift
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 [-d] [--model <model_name>] [--install-deps]"
      exit 1
      ;;
  esac
done

if [[ "$INSTALL_DEPS" == "true" ]]; then
  install_deps
fi

# Write a .env file from .env.example if one doesn't exist yet
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

export DEFAULT_MODEL="$SELECTED_MODEL"

echo "Starting budget-ai stack with model: $SELECTED_MODEL"
podman compose up --build $DETACH
