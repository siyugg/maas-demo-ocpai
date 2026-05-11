"""
FastAPI Backend-for-Frontend (BFF) for the MaaS Weather Demo.

Responsibilities:
  - POST /chat              Context-injection chat with SSE streaming (single LLM pass)
  - GET  /weather/map-data  Consolidated weather data for the Singapore map (60s cache)
  - GET  /admin/metrics     Both models' vLLM metrics in one JSON response
  - GET  /admin/info        InferenceService metadata + MCP tools list
  - GET  /admin/mcp/log     SSE stream of live MCP tool call events
  - POST /admin/mcp-test    Manual MCP tool invocation
  - GET  /health            Liveness probe
"""
import asyncio
import json
import logging
import time
from typing import AsyncIterator, Optional

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import mcp_client
from config import CORS_ORIGINS, MODELS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("bff")

app = FastAPI(title="MaaS Demo BFF", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Startup: pre-fetch MCP tools
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup():
    # Pre-warm weather cache so the first chat response is instant
    try:
        weather = await _get_cached_weather()
        logger.info("Weather cache warmed: %d area forecasts", len(weather.get("forecasts", {})))
    except Exception as exc:
        logger.warning("Weather cache warm-up failed (will retry on first request): %s", exc)

    # Pre-open MCP session (non-fatal if MCP server isn't ready yet)
    try:
        tools = await mcp_client.get_tools()
        logger.info("MCP tools loaded: %s", [t["name"] for t in tools])
    except Exception as exc:
        logger.warning("MCP tools pre-fetch failed (will retry on first request): %s", exc)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    model: str = "granite"  # "granite" | "qwen"


class McpTestRequest(BaseModel):
    tool: str
    arguments: dict = {}


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Weather data cache  (shared between /chat context injection and /weather/map-data)
# ---------------------------------------------------------------------------
_weather_cache: Optional[dict] = None
_weather_cache_time: float = 0
WEATHER_CACHE_TTL = 60  # seconds

_weather_cache_lock = asyncio.Lock()


async def _get_cached_weather() -> dict:
    """Return weather data, refreshing from data.gov.sg at most every 60s."""
    global _weather_cache, _weather_cache_time
    now = time.time()
    if _weather_cache and (now - _weather_cache_time) < WEATHER_CACHE_TTL:
        return _weather_cache
    async with _weather_cache_lock:
        # Double-check inside lock
        now = time.time()
        if _weather_cache and (now - _weather_cache_time) < WEATHER_CACHE_TTL:
            return _weather_cache
        raw = await _fetch_all_weather()
        _weather_cache = raw
        _weather_cache_time = now
        return raw


async def _fetch_all_weather() -> dict:
    """Fetch all weather endpoints concurrently."""
    API = "https://api-open.data.gov.sg/v2/real-time/api"
    async with httpx.AsyncClient(timeout=10) as client:
        two_hr, temp, humidity = await asyncio.gather(
            client.get(f"{API}/two-hr-forecast"),
            client.get(f"{API}/air-temperature"),
            client.get(f"{API}/relative-humidity"),
            return_exceptions=True,
        )

    result: dict = {}

    # 2-hour area forecasts
    if isinstance(two_hr, httpx.Response) and two_hr.status_code == 200:
        d = two_hr.json().get("data", {})
        items = d.get("items", [])
        if items:
            forecasts = {f["area"]: f["forecast"] for f in items[0].get("forecasts", [])}
            result["forecasts"] = forecasts
            result["forecast_valid_period"] = items[0].get("valid_period", {})
            result["area_metadata"] = d.get("area_metadata", [])

    # Real-time temperature readings
    if isinstance(temp, httpx.Response) and temp.status_code == 200:
        readings = temp.json().get("data", {}).get("readings", [])
        if readings:
            result["temperature"] = {
                r["stationId"]: r["value"]
                for r in readings[0].get("data", [])
            }
            result["stations"] = temp.json().get("data", {}).get("stations", [])

    # Real-time humidity readings
    if isinstance(humidity, httpx.Response) and humidity.status_code == 200:
        readings = humidity.json().get("data", {}).get("readings", [])
        if readings:
            result["humidity"] = {
                r["stationId"]: r["value"]
                for r in readings[0].get("data", [])
            }

    return result


def _build_weather_context(weather: dict) -> str:
    """Format cached weather data into a compact context block for the LLM."""
    lines = ["=== LIVE SINGAPORE WEATHER DATA ==="]

    forecasts = weather.get("forecasts", {})
    if forecasts:
        vp = weather.get("forecast_valid_period", {})
        period = f"{vp.get('start','')[:16]} – {vp.get('end','')[:16]}" if vp else "2-hour window"
        lines.append(f"\n2-Hour Area Forecasts ({period}):")
        for area, forecast in sorted(forecasts.items()):
            lines.append(f"  {area}: {forecast}")

    temps = weather.get("temperature", {})
    stations = {s["id"]: s["name"] for s in weather.get("stations", [])}
    if temps:
        lines.append("\nReal-Time Temperature (°C):")
        for sid, val in sorted(temps.items()):
            name = stations.get(sid, sid)
            lines.append(f"  {name}: {val}°C")

    humidity = weather.get("humidity", {})
    if humidity:
        lines.append("\nReal-Time Relative Humidity (%):")
        for sid, val in sorted(humidity.items()):
            name = stations.get(sid, sid)
            lines.append(f"  {name}: {val}%")

    lines.append("\n=== END WEATHER DATA ===")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# /chat  — context-injection SSE stream (single LLM pass, no tool calls)
# ---------------------------------------------------------------------------
def _sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


async def _run_agent(messages: list[dict], model_key: str) -> AsyncIterator[str]:
    """
    Fast single-pass approach:
      1. Pre-fetch all weather data from the 60s server-side cache
      2. Inject it into the system prompt as structured context
      3. Single LLM inference call — no tool call round trips
    This eliminates the 3-5x latency multiplier of the agentic loop.
    MCP tool calls are still available via /admin/mcp-test for the demo panel.
    """
    model_cfg = MODELS.get(model_key)
    if not model_cfg:
        yield _sse("error", {"message": f"Unknown model: {model_key}"})
        return

    # Pre-fetch weather data (non-blocking thanks to cache)
    try:
        weather = await _get_cached_weather()
        weather_context = _build_weather_context(weather)
        # Emit a synthetic tool_call/tool_result for the MCP monitor panel
        areas_mentioned = list(weather.get("forecasts", {}).keys())
        yield _sse("tool_call", {"tool": "weather_context_fetch", "args": {"cached": True}})
        yield _sse("tool_result", {"tool": "weather_context_fetch",
                                   "preview": f"{len(weather.get('forecasts', {}))} area forecasts loaded"})
        if areas_mentioned:
            yield _sse("map_update", {"areas": areas_mentioned})
    except Exception as exc:
        logger.warning("Weather pre-fetch failed, proceeding without context: %s", exc)
        weather_context = "(Weather data unavailable — answer from general knowledge.)"

    system_msg = {
        "role": "system",
        "content": (
            "You are a concise Singapore weather assistant. "
            "The live weather data below has already been fetched for you — use it directly to answer. "
            "Give a short, direct answer in 2-4 sentences. "
            "Always mention the specific area and time period.\n\n"
            + weather_context
        ),
    }
    history = [system_msg] + [m.copy() for m in messages]

    verify_ssl = model_cfg.get("verify_ssl", True)
    headers = {"Content-Type": "application/json"}
    if model_cfg["api_key"]:
        headers["Authorization"] = f"Bearer {model_cfg['api_key']}"

    payload = {
        "model": model_cfg["model_name"],
        "messages": history,
        "stream": True,
        "temperature": 0.3,
        "max_tokens": 512,
    }

    async with httpx.AsyncClient(timeout=60, verify=verify_ssl) as client:
        async with client.stream(
            "POST",
            f"{model_cfg['endpoint']}/chat/completions",
            headers=headers,
            json=payload,
        ) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                yield _sse("error", {"message": f"Model error {resp.status_code}: {body.decode()[:200]}"})
                return

            async for raw_line in resp.aiter_lines():
                if not raw_line or not raw_line.startswith("data: "):
                    continue
                chunk_str = raw_line[6:]
                if chunk_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(chunk_str)
                except json.JSONDecodeError:
                    continue

                delta = chunk.get("choices", [{}])[0].get("delta", {})
                if delta.get("content"):
                    yield _sse("token", {"text": delta["content"], "model": model_key})

    yield _sse("done", {"model": model_key, "model_label": model_cfg["label"]})


@app.post("/chat")
async def chat(req: ChatRequest):
    if req.model not in MODELS:
        raise HTTPException(status_code=400, detail=f"Model '{req.model}' is not configured.")
    messages = [m.model_dump() for m in req.messages]
    return StreamingResponse(
        _run_agent(messages, req.model),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# /weather/map-data  — served from the shared 60s weather cache
# ---------------------------------------------------------------------------
@app.get("/weather/map-data")
async def weather_map_data():
    try:
        weather = await _get_cached_weather()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    forecasts = weather.get("forecasts", {})
    area_meta = weather.get("area_metadata", [])
    vp = weather.get("forecast_valid_period", {})

    # Build area list with coordinates for the Leaflet map
    areas = [
        {
            "name": a["name"],
            "lat": a["label_location"]["latitude"],
            "lng": a["label_location"]["longitude"],
            "forecast": forecasts.get(a["name"], "N/A"),
        }
        for a in area_meta
    ]

    return {
        "timestamp": vp.get("start", ""),
        "valid_period": vp,
        "areas": areas,
        "cached_at": _weather_cache_time,
    }


# ---------------------------------------------------------------------------
# /admin/metrics  — both models' vLLM metrics
# ---------------------------------------------------------------------------
VLLM_METRIC_NAMES = [
    "vllm:generation_tokens_total",
    "vllm:prompt_tokens_total",
    "vllm:e2e_request_latency_seconds_sum",
    "vllm:e2e_request_latency_seconds_count",
    "vllm:gpu_cache_usage_perc",
    "vllm:num_requests_running",
    "vllm:num_requests_waiting",
]


def _parse_prometheus_text(text: str) -> dict:
    metrics = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#") or not line:
            continue
        parts = line.split(" ")
        if len(parts) >= 2:
            key = parts[0].split("{")[0]
            try:
                val = float(parts[-1])
                if key in VLLM_METRIC_NAMES:
                    metrics[key] = val
            except ValueError:
                pass
    return metrics


async def _fetch_model_metrics(model_key: str) -> dict:
    cfg = MODELS.get(model_key)
    if not cfg:
        return {"model": model_key, "status": "error", "error": "Model not configured", "timestamp": time.time()}
    # vLLM exposes /metrics on the same port as the inference endpoint
    metrics_url = cfg["endpoint"].replace("/v1", "") + "/metrics"
    headers = {}
    if cfg["api_key"]:
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    verify_ssl = cfg.get("verify_ssl", True)
    try:
        async with httpx.AsyncClient(timeout=5, verify=verify_ssl) as client:
            resp = await client.get(metrics_url, headers=headers)
            resp.raise_for_status()
            raw = _parse_prometheus_text(resp.text)

            # Compute derived metrics
            lat_sum = raw.get("vllm:e2e_request_latency_seconds_sum", 0)
            lat_count = raw.get("vllm:e2e_request_latency_seconds_count", 0)
            avg_latency = (lat_sum / lat_count) if lat_count > 0 else 0

            return {
                "model": model_key,
                "label": cfg["label"],
                "namespace": cfg["namespace"],
                "status": "ok",
                "tokens_total": raw.get("vllm:generation_tokens_total", 0),
                "prompt_tokens_total": raw.get("vllm:prompt_tokens_total", 0),
                "avg_latency_s": round(avg_latency, 3),
                "gpu_cache_perc": raw.get("vllm:gpu_cache_usage_perc", 0),
                "requests_running": int(raw.get("vllm:num_requests_running", 0)),
                "requests_waiting": int(raw.get("vllm:num_requests_waiting", 0)),
                "timestamp": time.time(),
            }
    except Exception as exc:
        return {
            "model": model_key,
            "label": cfg["label"],
            "namespace": cfg["namespace"],
            "status": "error",
            "error": str(exc),
            "timestamp": time.time(),
        }


@app.get("/admin/metrics")
async def admin_metrics():
    tasks = {key: _fetch_model_metrics(key) for key in MODELS}
    results = await asyncio.gather(*tasks.values())
    return dict(zip(tasks.keys(), results))


# ---------------------------------------------------------------------------
# /admin/info  — InferenceService metadata + MCP tools
# ---------------------------------------------------------------------------
@app.get("/admin/info")
async def admin_info():
    tools, mcp_health = await asyncio.gather(
        mcp_client.get_tools(),
        mcp_client.get_mcp_health(),
    )
    return {
        "models": {
            k: {
                "label": v["label"],
                "endpoint": v["endpoint"],
                "namespace": v["namespace"],
                "model_name": v["model_name"],
                "enabled": v.get("enabled", True),
            }
            for k, v in MODELS.items()
        },
        "available_models": list(MODELS.keys()),
        "mcp": {
            "health": mcp_health,
            "tools": tools,
        },
    }


# ---------------------------------------------------------------------------
# /admin/mcp/log  — SSE stream of live tool call events
# ---------------------------------------------------------------------------
@app.get("/admin/mcp/log")
async def admin_mcp_log():
    async def event_stream():
        # Send existing log first
        for entry in mcp_client.get_call_log():
            yield f"event: tool_call\ndata: {json.dumps(entry)}\n\n"

        q = mcp_client.subscribe_call_log()
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=30)
                    yield f"event: tool_call\ndata: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield "event: ping\ndata: {}\n\n"
        finally:
            mcp_client.unsubscribe_call_log(q)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# /admin/mcp-test  — manual tool invocation
# ---------------------------------------------------------------------------
@app.post("/admin/mcp-test")
async def admin_mcp_test(req: McpTestRequest):
    try:
        result = await mcp_client.call_tool(req.tool, req.arguments)
        return {"success": True, "result": result}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
