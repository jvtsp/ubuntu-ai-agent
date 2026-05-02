#!/bin/bash
# =============================================================================
# Ubuntu Agent - Script de inicialização
# =============================================================================
# Uso: ./run.sh
# Este script cria o ambiente virtual, instala dependências, verifica o LLM
# e inicia a aplicação.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"
CONFIG_FILE="${SCRIPT_DIR}/config.yaml"
PYTHON="python3"

# Cores para output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERRO]${NC} $*"; }

# ─── Verificar Python 3.12+ ─────────────────────────────────────────────────
if ! command -v "${PYTHON}" &>/dev/null; then
    error "Python 3 não encontrado. Instale com: sudo apt install python3"
    exit 1
fi

PY_VERSION=$("${PYTHON}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$("${PYTHON}" -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$("${PYTHON}" -c 'import sys; print(sys.version_info.minor)')

if [[ "${PY_MAJOR}" -lt 3 ]] || [[ "${PY_MINOR}" -lt 12 ]]; then
    error "Python 3.12+ é necessário. Versão encontrada: ${PY_VERSION}"
    exit 1
fi
info "Python ${PY_VERSION} encontrado."

# ─── Criar ambiente virtual ─────────────────────────────────────────────────
if [[ ! -d "${VENV_DIR}" ]]; then
    info "Criando ambiente virtual em ${VENV_DIR}..."
    if ! "${PYTHON}" -m venv --system-site-packages "${VENV_DIR}" 2>/dev/null; then
        warn "ensurepip não disponível. Criando venv sem pip..."
        "${PYTHON}" -m venv --system-site-packages --without-pip "${VENV_DIR}"
    fi
fi

# Ativar o venv
# shellcheck source=/dev/null
source "${VENV_DIR}/bin/activate"
info "Ambiente virtual ativado."

# ─── Garantir que pip está instalado ─────────────────────────────────────────
if ! command -v pip &>/dev/null; then
    info "Instalando pip via get-pip.py..."
    curl -sS https://bootstrap.pypa.io/get-pip.py | "${PYTHON}"
fi

# ─── Instalar dependências ──────────────────────────────────────────────────
if [[ -f "${SCRIPT_DIR}/requirements.txt" ]]; then
    info "Instalando dependências..."
    pip install --quiet --upgrade pip
    pip install --quiet -r "${SCRIPT_DIR}/requirements.txt"
    info "Dependências instaladas."
else
    error "requirements.txt não encontrado!"
    exit 1
fi

# ─── Criar diretório de dados ───────────────────────────────────────────────
mkdir -p "${SCRIPT_DIR}/data"

# ─── Health check do LLM ────────────────────────────────────────────────────
# Extrair base_url do config.yaml (sem depender de yq)
LLM_BASE_URL=$("${PYTHON}" -c "
import yaml, sys
with open('${CONFIG_FILE}') as f:
    cfg = yaml.safe_load(f)
print(cfg.get('llm', {}).get('base_url', 'http://localhost:11434/v1'))
")

# Extrair model do config.yaml
LLM_MODEL=$("${PYTHON}" -c "
import yaml, sys
with open('${CONFIG_FILE}') as f:
    cfg = yaml.safe_load(f)
print(cfg.get('llm', {}).get('model', ''))
")

# Remover /v1 do final para checar a raiz do servidor
LLM_ROOT="${LLM_BASE_URL%/v1}"
LLM_ROOT="${LLM_ROOT%/}"

info "Verificando endpoint LLM em ${LLM_ROOT}..."

if curl --silent --fail --max-time 5 "${LLM_ROOT}/api/tags" > /dev/null 2>&1; then
    info "LLM endpoint acessível (Ollama) ✓"
    if [[ -n "${LLM_MODEL}" ]]; then
        info "Garantindo que o modelo '${LLM_MODEL}' está baixado (Ollama Pull)..."
        if command -v ollama &>/dev/null; then
            ollama pull "${LLM_MODEL}" || warn "Falha ao baixar modelo ${LLM_MODEL}."
        else
            warn "Comando 'ollama' local não encontrado para realizar o pull automático."
        fi
    fi
elif curl --silent --fail --max-time 5 "${LLM_ROOT}" > /dev/null 2>&1; then
    info "LLM endpoint acessível ✓"
else
    warn "LLM endpoint NÃO acessível em ${LLM_ROOT}."
    warn "A aplicação iniciará, mas o agente não funcionará até o LLM estar online."
    warn "Certifique-se de que o Ollama/LM Studio está rodando."
fi

# ─── Iniciar a aplicação ────────────────────────────────────────────────────
info "Iniciando Ubuntu Agent..."
cd "${SCRIPT_DIR}"
"${PYTHON}" main.py "$@"
