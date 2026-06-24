#!/usr/bin/env bash
# =============================================================================
# setup.sh — Enterprise Decision Intelligence Platform Bootstrap
# =============================================================================
# Usage: bash setup.sh
# Tested on: Ubuntu 22+, Termux (Android), macOS 13+
# =============================================================================

set -euo pipefail

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║   Enterprise Decision Intelligence Platform — Setup          ║"
echo "║   v2.0.0  |  8-Agent Multi-Domain Pipeline                  ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── Python version check ──────────────────────────────────────────────────────
info "Checking Python version…"
PYTHON=$(command -v python3 || command -v python || error "Python not found")
PY_VERSION=$($PYTHON --version 2>&1 | awk '{print $2}')
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
if [ "$PY_MAJOR" -lt 3 ] || [ "$PY_MINOR" -lt 9 ]; then
    error "Python 3.9+ required. Found: $PY_VERSION"
fi
success "Python $PY_VERSION"

# ── Directory structure ───────────────────────────────────────────────────────
info "Creating directory structure…"
mkdir -p agents core services storage ui tests logs reports
touch agents/__init__.py core/__init__.py services/__init__.py
touch storage/__init__.py ui/__init__.py tests/__init__.py
touch storage/global_state.json storage/audit_log.json
echo "[]" > storage/audit_log.json
echo "{}" > storage/global_state.json
success "Directory structure ready"

# ── Virtual environment ───────────────────────────────────────────────────────
info "Setting up virtual environment…"
if [ ! -d ".venv" ]; then
    $PYTHON -m venv .venv
    success "Virtual environment created at .venv/"
else
    warn "Virtual environment already exists — skipping creation"
fi

# Activate
if [ -f ".venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
    PYTHON=".venv/bin/python"
elif [ -f ".venv/Scripts/activate" ]; then
    # Windows Git Bash
    # shellcheck disable=SC1091
    source .venv/Scripts/activate
    PYTHON=".venv/Scripts/python"
fi

# ── Dependencies ──────────────────────────────────────────────────────────────
info "Installing Python dependencies…"
$PYTHON -m pip install --upgrade pip --quiet

# Termux-specific: some packages need --break-system-packages
if command -v termux-info &>/dev/null; then
    warn "Termux detected — using --break-system-packages flag"
    INSTALL_FLAGS="--break-system-packages --quiet"
else
    INSTALL_FLAGS="--quiet"
fi

$PYTHON -m pip install $INSTALL_FLAGS -r requirements.txt
success "Dependencies installed"

# ── Environment file ──────────────────────────────────────────────────────────
info "Checking .env configuration…"
if [ ! -f ".env" ]; then
    cp .env.example .env
    warn ".env created from template — EDIT IT NOW and add your GROQ_API_KEY"
    echo ""
    echo "  ┌─────────────────────────────────────────────────────┐"
    echo "  │  Open .env and replace:                             │"
    echo "  │    GROQ_API_KEY=your_groq_api_key_here              │"
    echo "  │  with your real key from https://console.groq.com   │"
    echo "  └─────────────────────────────────────────────────────┘"
    echo ""
else
    success ".env already exists"
fi

# ── Database initialisation ───────────────────────────────────────────────────
info "Initialising database…"
$PYTHON -c "
import sys
sys.path.insert(0, '.')
from storage.database import Database
db = Database()
print('  Database tables created successfully.')
"
success "Database ready at storage/enterprise_maas.db"

# ── Final summary ─────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║   Setup complete!                                            ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║                                                              ║"
echo "║  1. Edit .env and add your GROQ_API_KEY                     ║"
echo "║                                                              ║"
echo "║  2. Launch the Streamlit dashboard:                          ║"
echo "║     streamlit run streamlit_app.py                           ║"
echo "║                                                              ║"
echo "║  3. Or run the CLI pipeline:                                 ║"
echo "║     python app.py                                            ║"
echo "║     python app.py --json output.json --pdf report.pdf        ║"
echo "║     python app.py --health                                   ║"
echo "║                                                              ║"
echo "║  4. Run tests:                                               ║"
echo "║     python -m pytest tests/ -v                               ║"
echo "║                                                              ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
