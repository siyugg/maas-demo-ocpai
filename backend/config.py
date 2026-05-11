"""Central config loaded from environment variables."""
import os
from dotenv import load_dotenv

load_dotenv()

# Granite-8B (maas-demo namespace)
# Use internal cluster URL when running in-cluster; falls back to external URL
GRANITE_ENDPOINT = os.getenv(
    "GRANITE_ENDPOINT",
    "https://granite-8b-predictor.maas-demo.svc.cluster.local:8443/v1",
)
GRANITE_API_KEY = os.getenv("GRANITE_API_KEY", "")
GRANITE_MODEL_NAME = os.getenv("GRANITE_MODEL_NAME", "granite-8b")
# Disable SSL verification for in-cluster self-signed certs (set to "true" to enable)
GRANITE_VERIFY_SSL = os.getenv("GRANITE_VERIFY_SSL", "false").lower() == "true"

# Qwen3-8B (maas-demo namespace) — optional, leave QWEN_ENDPOINT blank to disable
QWEN_ENDPOINT = os.getenv("QWEN_ENDPOINT", "")
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
QWEN_MODEL_NAME = os.getenv("QWEN_MODEL_NAME", "qwen3-8b")
QWEN_VERIFY_SSL = os.getenv("QWEN_VERIFY_SSL", "false").lower() == "true"

# MCP server (in-cluster)
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://mcp-server.maas-demo.svc.cluster.local:8000")

# CORS origins (frontend)
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")

# Build active model registry — Qwen is omitted if QWEN_ENDPOINT is not configured
MODELS: dict = {
    "granite": {
        "id": "granite",
        "label": "Granite-8B",
        "endpoint": GRANITE_ENDPOINT,
        "api_key": GRANITE_API_KEY,
        "model_name": GRANITE_MODEL_NAME,
        "namespace": "maas-demo",
        "color": "#EE0000",
        "verify_ssl": GRANITE_VERIFY_SSL,
        "enabled": True,
    },
}

if QWEN_ENDPOINT:
    MODELS["qwen"] = {
        "id": "qwen",
        "label": "Qwen3-8B",
        "endpoint": QWEN_ENDPOINT,
        "api_key": QWEN_API_KEY,
        "model_name": QWEN_MODEL_NAME,
        "namespace": "maas-demo",
        "color": "#9333ea",
        "verify_ssl": QWEN_VERIFY_SSL,
        "enabled": True,
    }
