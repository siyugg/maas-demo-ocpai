# MaaS Demo — Red Hat OpenShift AI

A full-stack weather chatbot demonstrating **Model-as-a-Service** capabilities on Red Hat OpenShift AI.

**Live demo features:**
- Chat interface powered by Granite-8B and Qwen3-8B via vLLM on RHOAI
- Live Singapore weather data from [data.gov.sg](https://data.gov.sg) via an MCP server
- Interactive Singapore weather map synchronized with chat queries
- Admin panel showing live vLLM metrics for both models and MCP call logs

---

## Architecture

```
Browser (React)
    │
    ▼
Nginx (frontend pod)  ──proxy──►  FastAPI BFF (backend pod)
                                       │               │
                                  MCP Server      data.gov.sg API
                                  (weather tools)
                                       │
                          Granite-8B / Qwen3-8B
                          (RHOAI InferenceService / vLLM)
```

### Components

| Service | Language | Description |
|---------|----------|-------------|
| `frontend/` | React + Vite + Tailwind CSS | Two-tab SPA: User (chat + map) and Admin (metrics + MCP monitor) |
| `backend/` | Python FastAPI | BFF: pre-fetches weather, injects context, streams chat via SSE |
| `mcp-server/` | Python FastMCP | 5 weather tools over Streamable HTTP, wired to data.gov.sg |

### OpenShift resources (`openshift/`)

```
openshift/
  backend/          ConfigMap, Deployment, Service, HPA, ServiceAccount
  frontend/         Deployment, Service, Route
  mcp-server/       Deployment, Service
  maas-demo/        InferenceService (Granite-8B)
  monitoring/       ServiceMonitor (Prometheus scrape for vLLM metrics)
```

---

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| `oc` CLI | 4.14+ | Logged in to your OpenShift cluster |
| `podman` | 4+ | For building container images |
| `node` | 20 | For local frontend development |
| `python` | 3.11 | For local backend/mcp-server development |

---

## Quick Start — Deploy to OpenShift

### 1. Set cluster variables

```bash
export CLUSTER=apps.ocp.<your-cluster-domain>
export REGISTRY=default-route-openshift-image-registry.${CLUSTER}
export NAMESPACE=maas-demo
```

### 2. Enable the external image registry route (one-time)

```bash
oc patch configs.imageregistry.operator.openshift.io/cluster \
  --patch '{"spec":{"defaultRoute":true}}' --type=merge
```

### 3. Create the namespace and ImageStreams

```bash
oc new-project ${NAMESPACE} || oc project ${NAMESPACE}
oc create imagestream backend   -n ${NAMESPACE}
oc create imagestream frontend  -n ${NAMESPACE}
oc create imagestream mcp-server -n ${NAMESPACE}
```

### 4. Log in to the registry

```bash
oc registry login
podman login ${REGISTRY} --tls-verify=false
```

### 5. Build and push all images

```bash
BUILD_TIME=$(date +%Y%m%d-%H%M)

# MCP server (amd64)
podman build --platform linux/amd64 \
  -t ${REGISTRY}/${NAMESPACE}/mcp-server:latest ./mcp-server
podman push ${REGISTRY}/${NAMESPACE}/mcp-server:latest --tls-verify=false

# Backend (amd64)
podman build --platform linux/amd64 \
  -t ${REGISTRY}/${NAMESPACE}/backend:latest ./backend
podman push ${REGISTRY}/${NAMESPACE}/backend:latest --tls-verify=false

# Frontend — two-step build (ARM64 native assets → amd64 nginx image)
cd frontend
podman build --target builder -t frontend-builder:local .
CID=$(podman create frontend-builder:local)
podman cp ${CID}:/app/dist ./dist
podman rm ${CID}
podman build --platform linux/amd64 \
  --build-arg BUILD_TIME=${BUILD_TIME} \
  -t ${REGISTRY}/${NAMESPACE}/frontend:latest \
  -f - . <<'EOF'
FROM registry.access.redhat.com/ubi9/nginx-120:latest
COPY dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/nginx.conf
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
EOF
podman push ${REGISTRY}/${NAMESPACE}/frontend:latest --tls-verify=false
cd ..
```

> **Why the two-step frontend build?**
> Vite uses esbuild (a Go binary) which crashes under QEMU emulation on Apple Silicon.
> The solution: build the JS assets natively (ARM64), extract the `dist/` folder,
> then package them into an amd64 Nginx image without any JS execution.

### 6. Deploy all resources

```bash
oc apply -k . -n ${NAMESPACE}
```

Or individually:

```bash
oc apply -f openshift/backend/    -n ${NAMESPACE}
oc apply -f openshift/frontend/   -n ${NAMESPACE}
oc apply -f openshift/mcp-server/ -n ${NAMESPACE}
```

### 7. Get the app URL

```bash
oc get route frontend -n ${NAMESPACE} -o jsonpath='{.spec.host}'
```

---

## Update a Single Service (after code changes)

### Backend only

```bash
podman build --platform linux/amd64 -t ${REGISTRY}/${NAMESPACE}/backend:latest ./backend
podman push ${REGISTRY}/${NAMESPACE}/backend:latest --tls-verify=false
oc rollout restart deployment/backend -n ${NAMESPACE}
```

### Frontend only

```bash
cd frontend
podman build --target builder -t frontend-builder:local .
CID=$(podman create frontend-builder:local)
podman cp ${CID}:/app/dist ./dist && podman rm ${CID}
podman build --platform linux/amd64 \
  --build-arg BUILD_TIME=$(date +%Y%m%d-%H%M) \
  -t ${REGISTRY}/${NAMESPACE}/frontend:latest \
  -f - . <<'EOF'
FROM registry.access.redhat.com/ubi9/nginx-120:latest
COPY dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/nginx.conf
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
EOF
podman push ${REGISTRY}/${NAMESPACE}/frontend:latest --tls-verify=false
oc rollout restart deployment/frontend -n ${NAMESPACE}
cd ..
```

### MCP server only

```bash
podman build --platform linux/amd64 -t ${REGISTRY}/${NAMESPACE}/mcp-server:latest ./mcp-server
podman push ${REGISTRY}/${NAMESPACE}/mcp-server:latest --tls-verify=false
oc rollout restart deployment/mcp-server -n ${NAMESPACE}
```

---

## Local Development

### 1. Copy and fill in environment variables

```bash
cp .env.example backend/.env
# Edit backend/.env — set GRANITE_ENDPOINT and GRANITE_API_KEY
```

### 2. Run the MCP server

```bash
cd mcp-server
pip install -r requirements.txt
python server.py
# Listening on http://localhost:8000
```

### 3. Run the backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8080
# Listening on http://localhost:8080
```

### 4. Run the frontend

```bash
cd frontend
npm install
npm run dev
# Listening on http://localhost:5173
```

---

## Secrets and Configuration

All secrets are stored as OpenShift Secrets and referenced by `secretKeyRef` in the Deployment — **no credentials are stored in this repository**.

| Secret name | Key | Used for |
|------------|-----|---------|
| `default-token-granite-8b-sa` | `token` | Granite-8B vLLM bearer token |
| `default-token-qwen3-8b-sa` | `token` | Qwen3-8B vLLM bearer token |

These secrets are auto-created by OpenShift when the model's ServiceAccount is created in RHOAI.

### Backend ConfigMap (`openshift/backend/configmap.yaml`)

| Key | Value | Notes |
|-----|-------|-------|
| `GRANITE_ENDPOINT` | `https://granite-8b-predictor.maas-demo.svc.cluster.local:8443/v1` | In-cluster |
| `GRANITE_MODEL_NAME` | `granite-8b` | Must match the InferenceService name |
| `GRANITE_VERIFY_SSL` | `false` | Self-signed cert inside cluster |
| `QWEN_ENDPOINT` | `https://qwen3-8b-predictor.maas-demo.svc.cluster.local:8443/v1` | In-cluster |
| `QWEN_MODEL_NAME` | `qwen3-8b` | Must match the InferenceService name |
| `QWEN_VERIFY_SSL` | `false` | Self-signed cert inside cluster |
| `MCP_SERVER_URL` | `http://mcp-server.maas-demo.svc.cluster.local:8000` | In-cluster |

To add a new model:
1. Deploy it in RHOAI as an InferenceService
2. Add its endpoint and model name to `configmap.yaml`
3. Add its SA token secret reference to `deployment.yaml`
4. Add it to `backend/config.py` `MODELS` dict
5. Rebuild and push the backend image

---

## Enabling / Disabling Qwen

Set `QWEN_ENDPOINT` to empty string in `configmap.yaml` to disable Qwen:

```yaml
QWEN_ENDPOINT: ""
```

Restore the full URL to re-enable it. No code changes needed.

---

## Monitoring

- **vLLM metrics**: Admin Panel → Metrics tab (fetches from `/metrics` on each model's endpoint)
- **MCP live call log**: Admin Panel → MCP Monitor tab (SSE stream of every tool call)
- **Prometheus**: A `ServiceMonitor` in `openshift/monitoring/` scrapes vLLM metrics automatically if the OpenShift User Workload Monitoring stack is enabled

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `404 model does not exist` | `GRANITE_MODEL_NAME` wrong | Check `oc get inferenceservice -n maas-demo` for the actual name |
| `406 Not Acceptable` from MCP | Old backend image without Accept header fix | Rebuild and push backend |
| `Exec format error` on pod start | Image built for wrong architecture | Rebuild with `--platform linux/amd64` |
| Map shows "failed to load" | data.gov.sg rate limit or network | Backend retries automatically; wait 60s |
| Chat history lost on tab switch | Browser serving old JS bundle | Hard refresh once (Cmd+Shift+R) |
| Pods in CrashLoopBackOff | Check logs: `oc logs -l app=backend -n maas-demo` | See error table above |
