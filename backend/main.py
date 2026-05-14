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
from fastapi import FastAPI, HTTPException
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
# /chat  — multi-model orchestration
# Granite -> weather specialist
# Qwen    -> transport specialist
# Final answer is synthesized after cross-model exchange.
# ---------------------------------------------------------------------------
def _sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def _extract_json_object(raw: str) -> Optional[dict]:
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        parsed = json.loads(raw[start : end + 1])
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        return None
    return None


def _normalize_confidence(value: object, default: float = 0.65) -> float:
    try:
        numeric = float(value)
        if numeric > 1.0:
            numeric = numeric / 100.0
        return max(0.0, min(1.0, numeric))
    except (TypeError, ValueError):
        return default


def _fallback_decision_card(user_query: str, granite_draft: str, qwen_draft: str) -> dict:
    joined = f"{granite_draft}\n{qwen_draft}".lower()
    if any(token in joined for token in ["thunder", "heavy rain", "storm", "flood"]):
        risk = "high"
    elif any(token in joined for token in ["rain", "wet", "congestion", "slow"]):
        risk = "medium"
    else:
        risk = "low"

    recommendation = "Follow public transit and monitor live conditions before departure."
    if qwen_draft.strip():
        recommendation = qwen_draft.split(".")[0].strip()[:180] or recommendation

    confidence = 0.72 if granite_draft.strip() and qwen_draft.strip() else 0.58
    why = [
        "Weather specialist assessed near-term rain and humidity risk.",
        "Transport specialist reviewed LTA congestion/peak-hour context.",
        f"Advice is tailored to your request: {user_query[:80]}",
    ]
    return {
        "risk_level": risk,
        "recommended_action": recommendation,
        "confidence": confidence,
        "why": why,
    }


def _normalize_decision_card(decision_card: dict) -> dict:
    card = dict(decision_card)
    card["confidence"] = _normalize_confidence(card.get("confidence"))
    card["why"] = [str(item) for item in card.get("why", []) if str(item).strip()]
    card["redacted"] = False
    return card


async def _generate_decision_card(
    final_model: str,
    user_query: str,
    granite_draft: str,
    qwen_draft: str,
) -> dict:
    prompt = [
        {
            "role": "system",
            "content": (
                "Produce a machine-readable decision card as strict JSON only. "
                "Fields: risk_level (low|medium|high), recommended_action (string), "
                "confidence (0..1), why (array of 2-4 short strings)."
            ),
        },
        {
            "role": "user",
            "content": (
                f"User question:\n{user_query}\n\n"
                f"Weather specialist draft:\n{granite_draft or '(unavailable)'}\n\n"
                f"Transport specialist draft:\n{qwen_draft or '(unavailable)'}"
            ),
        },
    ]

    fallback = _fallback_decision_card(user_query, granite_draft, qwen_draft)
    try:
        raw = await _chat_once(final_model, prompt, temperature=0.1, max_tokens=180)
        parsed = _extract_json_object(raw) or {}
        if not parsed:
            return _normalize_decision_card(fallback)
        candidate = {
            "risk_level": str(parsed.get("risk_level", fallback["risk_level"])).lower(),
            "recommended_action": str(parsed.get("recommended_action", fallback["recommended_action"])),
            "confidence": _normalize_confidence(parsed.get("confidence"), fallback["confidence"]),
            "why": parsed.get("why", fallback["why"]),
        }
        return _normalize_decision_card(candidate)
    except Exception as exc:
        logger.warning("Decision card generation failed, using fallback: %s", exc)
        return _normalize_decision_card(fallback)


async def _chat_once(model_key: str, history: list[dict], temperature: float = 0.2, max_tokens: int = 450) -> str:
    """Run one non-streaming chat completion and return text."""
    model_cfg = MODELS.get(model_key)
    if not model_cfg:
        raise ValueError(f"Unknown model: {model_key}")
    verify_ssl = model_cfg.get("verify_ssl", True)
    headers = {"Content-Type": "application/json"}
    if model_cfg["api_key"]:
        headers["Authorization"] = f"Bearer {model_cfg['api_key']}"
    payload = {
        "model": model_cfg["model_name"],
        "messages": history,
        "stream": False,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    async with httpx.AsyncClient(timeout=70, verify=verify_ssl) as client:
        resp = await client.post(
            f"{model_cfg['endpoint']}/chat/completions",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()


async def _stream_final_answer(model_key: str, history: list[dict]) -> AsyncIterator[str]:
    """Stream final synthesis response tokens."""
    model_cfg = MODELS.get(model_key)
    if not model_cfg:
        yield _sse("error", {"message": f"Unknown model: {model_key}"})
        return

    verify_ssl = model_cfg.get("verify_ssl", True)
    headers = {"Content-Type": "application/json"}
    if model_cfg["api_key"]:
        headers["Authorization"] = f"Bearer {model_cfg['api_key']}"
    payload = {
        "model": model_cfg["model_name"],
        "messages": history,
        "stream": True,
        "temperature": 0.25,
        "max_tokens": 600,
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
                    yield _sse("token", {"text": delta["content"], "model": model_key, "role": "fusion"})


async def _run_agent(messages: list[dict], model_key: str) -> AsyncIterator[str]:
    """
    Two-specialist orchestration:
      1) Granite analyzes weather
      2) Qwen analyzes LTA transport dataset
      3) Final model synthesizes both specialist outputs
    """
    user_query = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
    if not user_query:
        yield _sse("error", {"message": "No user query provided."})
        return

    request_start = time.perf_counter()
    phase_marks_ms: dict[str, int] = {}
    tools_used: list[str] = []
    weather: dict = {}

    def mark_phase(phase_name: str) -> int:
        elapsed_ms = round((time.perf_counter() - request_start) * 1000)
        phase_marks_ms[phase_name] = elapsed_ms
        return elapsed_ms

    def record_tool(tool_name: str):
        if tool_name not in tools_used:
            tools_used.append(tool_name)

    # --------------------------
    # Fetch weather context via MCP tools (direct tool-driven weather path)
    # --------------------------
    weather_context = "(Weather data unavailable.)"
    areas_mentioned: list[str] = []
    weather_segments: list[str] = []
    weather_tool_calls = [
        ("get_two_hour_forecast", {}),
        ("get_realtime_temperature", {}),
        ("get_realtime_humidity", {}),
    ]
    for tool_name, tool_args in weather_tool_calls:
        try:
            record_tool(tool_name)
            yield _sse("tool_call", {"tool": tool_name, "args": tool_args})
            result = await mcp_client.call_tool(tool_name, tool_args)
            weather_segments.append(f"{tool_name}:\n{result}")
            yield _sse("tool_result", {"tool": tool_name, "preview": str(result)[:220]})
        except Exception as exc:
            logger.warning("Weather MCP tool failed: %s", exc)
            yield _sse("tool_result", {"tool": tool_name, "preview": f"Error: {exc}"})

    if weather_segments:
        weather_context = "\n\n".join(weather_segments)

    # Use cached map payload only for highlighting/evidence metadata, not for specialist reasoning.
    try:
        weather = await _get_cached_weather()
        areas_mentioned = list(weather.get("forecasts", {}).keys())
        if areas_mentioned:
            yield _sse("map_update", {"areas": areas_mentioned})
    except Exception as exc:
        logger.warning("Weather metadata fetch failed: %s", exc)

    # --------------------------
    # Fetch LTA transport context via MCP tools
    # --------------------------
    transport_context = "(LTA transport data unavailable.)"
    try:
        record_tool("get_lta_peak_hour_summary")
        yield _sse("tool_call", {"tool": "get_lta_peak_hour_summary", "args": {"compare_years": 5}})
        transport_context = await mcp_client.call_tool("get_lta_peak_hour_summary", {"compare_years": 5})
        yield _sse("tool_result", {"tool": "get_lta_peak_hour_summary", "preview": str(transport_context)[:220]})
    except Exception as exc:
        logger.warning("LTA MCP tool failed: %s", exc)
        yield _sse("tool_result", {"tool": "get_lta_peak_hour_summary", "preview": f"Error: {exc}"})

    # --------------------------
    # Specialist 1: Granite (weather)
    # --------------------------
    granite_draft = ""
    if "granite" in MODELS:
        try:
            weather_phase_ms = mark_phase("weather_specialist")
            yield _sse("weather_specialist_start", {"phase": "weather_specialist", "t_ms": weather_phase_ms})
            record_tool("granite_weather_specialist")
            yield _sse("tool_call", {"tool": "granite_weather_specialist", "args": {}})
            granite_history = [
                {
                    "role": "system",
                    "content": (
                        "You are the weather specialist. Use only the provided weather context. "
                        "Give concise, factual weather insights relevant to the user's request."
                    ),
                },
                {
                    "role": "user",
                    "content": f"User question: {user_query}\n\nWeather context:\n{weather_context}",
                },
            ]
            granite_draft = await _chat_once("granite", granite_history, temperature=0.2, max_tokens=320)
            yield _sse("tool_result", {"tool": "granite_weather_specialist", "preview": granite_draft[:220]})
        except Exception as exc:
            logger.warning("Granite specialist failed: %s", exc)
            yield _sse("tool_result", {"tool": "granite_weather_specialist", "preview": f"Error: {exc}"})

    # --------------------------
    # Specialist 2: Qwen (transport), informed by Granite output
    # --------------------------
    qwen_draft = ""
    if "qwen" in MODELS:
        try:
            transport_phase_ms = mark_phase("transport_specialist")
            yield _sse("transport_specialist_start", {"phase": "transport_specialist", "t_ms": transport_phase_ms})
            record_tool("qwen_transport_specialist")
            yield _sse("tool_call", {"tool": "qwen_transport_specialist", "args": {}})
            qwen_history = [
                {
                    "role": "system",
                    "content": (
                        "You are the transport specialist. Use only the provided LTA context. "
                        "You may reference weather specialist notes to align recommendations."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"User question: {user_query}\n\n"
                        f"LTA transport context:\n{transport_context}\n\n"
                        f"Weather specialist notes:\n{granite_draft or '(none)'}"
                    ),
                },
            ]
            qwen_draft = await _chat_once("qwen", qwen_history, temperature=0.2, max_tokens=320)
            yield _sse("tool_result", {"tool": "qwen_transport_specialist", "preview": qwen_draft[:220]})
        except Exception as exc:
            logger.warning("Qwen specialist failed: %s", exc)
            yield _sse("tool_result", {"tool": "qwen_transport_specialist", "preview": f"Error: {exc}"})

    final_model = model_key if model_key in MODELS else ("granite" if "granite" in MODELS else next(iter(MODELS.keys())))
    final_model_cfg = MODELS[final_model]
    fusion_phase_ms = mark_phase("fusion")
    yield _sse("fusion_start", {"phase": "fusion", "t_ms": fusion_phase_ms})

    decision_card = await _generate_decision_card(
        final_model=final_model,
        user_query=user_query,
        granite_draft=granite_draft,
        qwen_draft=qwen_draft,
    )
    yield _sse("decision_card", decision_card)

    weather_period = weather.get("forecast_valid_period", {})
    evidence_payload = {
        "weather_timestamp": weather_period.get("start", ""),
        "weather_valid_period": weather_period,
        "transport_dataset": "LTA peak-hour summary (compare_years=5)",
        "tools_used": tools_used,
        "model_split": {
            "weather_specialist": MODELS["granite"]["label"] if "granite" in MODELS else "Unavailable",
            "transport_specialist": MODELS["qwen"]["label"] if "qwen" in MODELS else "Unavailable",
            "fusion": final_model_cfg["label"],
        },
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    # --------------------------
    # Final fusion (models "communicate" via exchanged specialist notes)
    # --------------------------
    fusion_history = [
        {
            "role": "system",
            "content": (
                "You are a coordinator that fuses specialist outputs into one final answer. "
                "Prioritize factual alignment, then provide practical user guidance. "
                "Keep it concise (4-7 bullets max) and mention assumptions. "
                "Always include a short 'Decision snapshot' block with Risk level, Recommended action, Confidence, and Why. "
                "Include explicit evidence references (weather timestamp/valid period and LTA dataset context)."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Original user question:\n{user_query}\n\n"
                f"Weather specialist (Granite):\n{granite_draft or '(unavailable)'}\n\n"
                f"Transport specialist (Qwen):\n{qwen_draft or '(unavailable)'}\n\n"
                "Produce one unified answer that combines weather + transport implications."
            ),
        },
    ]
    async for event in _stream_final_answer(final_model, fusion_history):
        yield event

    total_elapsed_ms = round((time.perf_counter() - request_start) * 1000)
    phase_latencies = {
        "weather_specialist": max(
            0,
            phase_marks_ms.get("transport_specialist", phase_marks_ms.get("fusion", total_elapsed_ms))
            - phase_marks_ms.get("weather_specialist", phase_marks_ms.get("fusion", total_elapsed_ms)),
        ),
        "transport_specialist": max(
            0,
            phase_marks_ms.get("fusion", total_elapsed_ms) - phase_marks_ms.get("transport_specialist", phase_marks_ms.get("fusion", total_elapsed_ms)),
        ),
        "fusion": max(0, total_elapsed_ms - phase_marks_ms.get("fusion", total_elapsed_ms)),
    }

    yield _sse(
        "done",
        {
            "model": final_model,
            "model_label": final_model_cfg["label"],
            "mode": "multi-model-fusion",
            "t_ms": total_elapsed_ms,
            "phase_latencies_ms": phase_latencies,
            "decision_card": decision_card,
            "evidence": evidence_payload,
        },
    )


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
    "vllm:time_to_first_token_seconds_sum",
    "vllm:time_to_first_token_seconds_count",
]

# Rolling counters for per-second rates
_model_rate_state: dict[str, dict[str, float]] = {}


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
            ttft_sum = raw.get("vllm:time_to_first_token_seconds_sum", 0)
            ttft_count = raw.get("vllm:time_to_first_token_seconds_count", 0)
            avg_ttft = (ttft_sum / ttft_count) if ttft_count > 0 else 0

            now = time.time()
            gen_total = raw.get("vllm:generation_tokens_total", 0)
            prompt_total = raw.get("vllm:prompt_tokens_total", 0)
            req_total = lat_count

            prev = _model_rate_state.get(model_key)
            generation_tps = 0.0
            prompt_tps = 0.0
            requests_per_s = 0.0
            if prev:
                dt = max(0.001, now - prev["ts"])
                generation_tps = max(0.0, (gen_total - prev["gen_total"]) / dt)
                prompt_tps = max(0.0, (prompt_total - prev["prompt_total"]) / dt)
                requests_per_s = max(0.0, (req_total - prev["req_total"]) / dt)
            _model_rate_state[model_key] = {
                "ts": now,
                "gen_total": gen_total,
                "prompt_total": prompt_total,
                "req_total": req_total,
            }

            running = int(raw.get("vllm:num_requests_running", 0))
            waiting = int(raw.get("vllm:num_requests_waiting", 0))
            queue_ratio = (waiting / (running + waiting)) if (running + waiting) > 0 else 0.0

            return {
                "model": model_key,
                "label": cfg["label"],
                "namespace": cfg["namespace"],
                "endpoint": cfg["endpoint"],
                "status": "ok",
                "tokens_total": gen_total,
                "prompt_tokens_total": prompt_total,
                "total_tokens": gen_total + prompt_total,
                "avg_latency_s": round(avg_latency, 3),
                "avg_ttft_s": round(avg_ttft, 3),
                "generation_tps": round(generation_tps, 2),
                "prompt_tps": round(prompt_tps, 2),
                "requests_per_s": round(requests_per_s, 3),
                "gpu_cache_perc": raw.get("vllm:gpu_cache_usage_perc", 0),
                "requests_running": running,
                "requests_waiting": waiting,
                "queue_ratio": round(queue_ratio, 3),
                "timestamp": now,
            }
    except Exception as exc:
        return {
            "model": model_key,
            "label": cfg["label"],
            "namespace": cfg["namespace"],
            "endpoint": cfg["endpoint"],
            "status": "error",
            "error": str(exc),
            "timestamp": time.time(),
        }


@app.get("/admin/metrics")
async def admin_metrics():
    tasks = {key: _fetch_model_metrics(key) for key in MODELS}
    results = await asyncio.gather(*tasks.values())
    models = dict(zip(tasks.keys(), results))

    ok_models = [m for m in models.values() if m.get("status") == "ok"]
    total_models = len(models)
    healthy_models = len(ok_models)
    requests_running_total = sum(int(m.get("requests_running", 0)) for m in ok_models)
    requests_waiting_total = sum(int(m.get("requests_waiting", 0)) for m in ok_models)
    generation_tps_total = round(sum(float(m.get("generation_tps", 0) or 0) for m in ok_models), 2)
    prompt_tps_total = round(sum(float(m.get("prompt_tps", 0) or 0) for m in ok_models), 2)
    avg_latency_s = round(
        (sum(float(m.get("avg_latency_s", 0) or 0) for m in ok_models) / healthy_models) if healthy_models else 0.0,
        3,
    )
    avg_ttft_s = round(
        (sum(float(m.get("avg_ttft_s", 0) or 0) for m in ok_models) / healthy_models) if healthy_models else 0.0,
        3,
    )

    call_log = mcp_client.get_call_log()
    recent_calls = len(call_log)
    failed_calls = sum(1 for e in call_log if not e.get("success", True))
    mcp_success_rate = round(((recent_calls - failed_calls) / recent_calls) if recent_calls else 1.0, 3)

    return {
        "fleet": {
            "models_total": total_models,
            "models_healthy": healthy_models,
            "requests_running_total": requests_running_total,
            "requests_waiting_total": requests_waiting_total,
            "generation_tps_total": generation_tps_total,
            "prompt_tps_total": prompt_tps_total,
            "avg_latency_s": avg_latency_s,
            "avg_ttft_s": avg_ttft_s,
            "mcp_recent_calls": recent_calls,
            "mcp_success_rate": mcp_success_rate,
            "timestamp": time.time(),
        },
        "models": models,
    }


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
