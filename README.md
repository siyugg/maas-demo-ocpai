# MaaS Demo — Red Hat OpenShift AI

A full-stack **Model as a Service** demo hosted on Red Hat OpenShift AI, featuring:

- **Live Singapore weather chat** powered by two LLMs (Granite-8B + Qwen3-8B)
- **MCP (Model Context Protocol) server** connecting the LLMs to real-time data.gov.sg weather APIs
- **Interactive Singapore map** that highlights areas mentioned in chat
- **Admin panel** with live vLLM metrics for both models and a full MCP monitor

---

## Architecture

```
Browser
  │
  ▼
Frontend (React + Vite)          ← OpenShift Route (HTTPS)
  │  nginx proxies /chat, /weather, /admin to backend
  ▼
Backend BFF (FastAPI)            ← maas-demo namespace
  │  Agentic loop: LLM ↔ MCP
  ├─── Granite-8B InferenceService (maas-demo ns)
  ├─── Qwen3-8B InferenceService  (marketing-intern ns, via Route)
  └─── MCP Weather Server         (maas-demo ns)
         │
         └─── api-open.data.gov.sg  (2-hour, 24-hour, 4-day forecast, temp, humidity)
```

---

## Prerequisites

- OpenShift cluster with **Red Hat OpenShift AI** operator installed
- `oc` CLI authenticated to the cluster
- `podman` for building images
- Granite-8B deployed in `maas-demo` namespace (InferenceService name: `granite-8b`)
- Qwen3-8B deployed in `marketing-intern` namespace (InferenceService name: `qwen3-8b`)
- OpenShift internal image registry accessible

---

## Quick Start

### 1. Set up secrets

Fill in your credentials:

```bash
# Backend secrets (model Bearer tokens + Qwen endpoint)
cp openshift/backend/secret-template.yaml openshift/backend/secret.yaml
# Edit secret.yaml: add GRANITE_API_KEY, QWEN_API_KEY, QWEN_ENDPOINT

# MCP server secret (optional: data.gov.sg API key for higher rate limits)
cp openshift/mcp-server/secret-template.yaml openshift/mcp-server/secret.yaml
# Edit secret.yaml: add api-key if you have one
```

> **Finding model Bearer tokens:**  
> In the OpenShift AI dashboard → your project → the deployed model → copy the token shown under "Inference endpoint".

### 2. Get the Qwen3-8B Route URL

```bash
oc get route -n marketing-intern | grep qwen
```

Paste the full HTTPS URL into `openshift/backend/secret.yaml` as `QWEN_ENDPOINT`.

### 3. Build and deploy

```bash
# Log in to the internal registry
oc registry login

make all
```

Or step by step:

```bash
make build    # podman build all three images
make push     # push to OpenShift internal registry
make deploy   # oc apply -k .
```

### 4. Open the demo

```bash
make url      # prints the frontend Route URL
```

---

## Component Details

### MCP Weather Server (`mcp-server/`)

Python service using the official `mcp` SDK with **Streamable HTTP** transport.

| Tool | Description | API endpoint |
|------|-------------|--------------|
| `get_two_hour_forecast` | 2-hour area forecast (all 47 areas or filter by name) | `/two-hr-forecast` |
| `get_twenty_four_hour_forecast` | Full-day outlook with temp, humidity, wind | `/twenty-four-hr-forecast` |
| `get_four_day_forecast` | 4-day medium-range forecast | `/four-day-weather-forecast` |
| `get_realtime_temperature` | Live °C readings from NEA stations | `/air-temperature` |
| `get_realtime_humidity` | Live % humidity from NEA stations | `/relative-humidity` |

### Backend BFF (`backend/`)

FastAPI service acting as:
- **MCP client** — discovers tools on startup, executes them during agentic loops
- **LLM orchestrator** — routes chat to the selected model, injects tool results back
- **SSE streamer** — streams tokens + tool call events + map highlight events to frontend
- **Admin API** — proxies vLLM `/metrics`, aggregates MCP call log via SSE

### Frontend (`frontend/`)

React + Vite + Tailwind with two tabs:

**User Tab**
- Left: Chat with `Granite ⇄ Qwen` toggle, streaming responses, collapsible MCP tool call disclosure
- Right: Leaflet.js map of Singapore — 47 area markers color-coded by forecast, highlights areas mentioned in chat, refreshes every 30s

**Admin Panel**
- Left: Live vLLM metrics for both models simultaneously (tokens/sec, latency, GPU KV cache, active requests) with a shared comparison chart
- Right: MCP Monitor — server health badge, tool registry with JSON schemas, live call log (SSE stream), per-tool call count bars, manual test-call form

---

## Development (local)

```bash
# Start MCP server
cd mcp-server && pip install -r requirements.txt
uvicorn server:app --port 8000 --reload

# Start backend (set env vars first)
cd backend
cp ../.env.example .env  # fill in RHOAI endpoints + keys
pip install -r requirements.txt
uvicorn main:app --port 8080 --reload

# Start frontend
cd frontend && npm install
npm run dev   # proxies /chat etc. to :8080
```

---

## Environment Variables

| Variable | Service | Description |
|----------|---------|-------------|
| `GRANITE_ENDPOINT` | backend | Granite-8B `/v1` inference URL |
| `GRANITE_API_KEY` | backend | Bearer token for Granite-8B |
| `GRANITE_MODEL_NAME` | backend | Model ID string for the API call |
| `QWEN_ENDPOINT` | backend | Qwen3-8B `/v1` inference URL (Route) |
| `QWEN_API_KEY` | backend | Bearer token for Qwen3-8B |
| `QWEN_MODEL_NAME` | backend | Model ID string for the API call |
| `MCP_SERVER_URL` | backend | Internal cluster URL of MCP server |
| `CORS_ORIGINS` | backend | Comma-separated allowed origins |
| `DATA_GOV_SG_API_KEY` | mcp-server | Optional API key for data.gov.sg |

---

## OpenShift AI Capabilities Demonstrated

| Capability | Where shown |
|-----------|-------------|
| KServe single-model serving (RawDeployment) | Both InferenceService YAMLs |
| vLLM ServingRuntime with OpenAI-compatible API | Chat completions in BFF |
| Bearer token auth on inference routes | `GRANITE_API_KEY` / `QWEN_API_KEY` |
| ServiceMonitor for Prometheus scraping | `monitoring/` manifests |
| Multi-model comparison | Admin panel metrics cards |
| HorizontalPodAutoscaler on BFF | `backend/hpa.yaml` |
| Liveness/readiness probes on all workloads | All deployment YAMLs |
| OpenShift Route with TLS edge termination | `frontend/route.yaml` |
| UBI-based container images | All Dockerfiles |
