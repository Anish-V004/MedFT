"""
config.py — All settings loaded from pv_frontend/.env

Copy .env.example to .env and fill in your values before running the app.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from this folder (pv_frontend/.env), not from project root
load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)

def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise RuntimeError(f"Missing required env var: {key}. Check medassist_app/.env")
    return val

def _get(key: str, default: str) -> str:
    return os.getenv(key, default)

# ─── Fine-Tuned PV Model ──────────────────────────────────────────────────────
JUPYTER_BASE_URL         = _require("JUPYTER_BASE_URL")
JUPYTER_TOKEN            = _require("JUPYTER_TOKEN")
FINETUNED_MODEL_BASE_URL = _require("FINETUNED_MODEL_BASE_URL")
FINETUNED_MODEL_NAME     = _require("FINETUNED_MODEL_NAME")
FINETUNED_API_KEY        = _get("FINETUNED_API_KEY", "dummy")
FINETUNED_MAX_TOKENS     = 1024
FINETUNED_TEMPERATURE    = 0.0  # Set to 0 for deterministic outputs
FINETUNED_TOP_P          = 0.9

# ─── Summary / Consolidation Model (Ollama Cloud) ────────────────────────────
BASE_MODEL_BASE_URL = _require("BASE_MODEL_BASE_URL")
BASE_MODEL_NAME     = _require("BASE_MODEL_NAME")
BASE_MODEL_API_KEY  = _require("BASE_MODEL_API_KEY")
BASE_MAX_TOKENS     = 2048
BASE_TEMPERATURE    = 0.3

# ─── RSI Mapping ─────────────────────────────────────────────────────────────
RSI_MAPPING_PATH = os.path.join(os.path.dirname(__file__), "rsi_mapping.json")

# ─── App ─────────────────────────────────────────────────────────────────────
APP_TITLE  = "MedAssist · Pharmacovigilance Review Assistant"
APP_HOST   = _get("APP_HOST", "0.0.0.0")
APP_PORT   = int(_get("APP_PORT", "7860"))
APP_SHARE  = _get("APP_SHARE", "false").lower() == "true"
