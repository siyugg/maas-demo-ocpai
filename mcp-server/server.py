"""
MCP Weather Server — data.gov.sg weather tools via Streamable HTTP transport.
Uses FastMCP's native run() lifecycle to avoid task-group initialization errors.
"""
import os
import logging
from datetime import datetime
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("mcp-weather")

API_BASE = "https://api-open.data.gov.sg/v2/real-time/api"
API_KEY = os.getenv("DATA_GOV_SG_API_KEY", "")

mcp = FastMCP(
    name="singapore-weather",
    host="0.0.0.0",
    port=8000,
    instructions=(
        "You have access to live Singapore weather data from NEA via data.gov.sg. "
        "Use the tools to answer weather questions with real-time data. "
        "Always mention the data timestamp in your answer."
    ),
)


def _headers() -> dict:
    h = {"Accept": "application/json"}
    if API_KEY:
        h["x-api-key"] = API_KEY
    return h


def _fmt_dt(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d %b %Y %H:%M SGT")
    except Exception:
        return iso


async def _get(path: str, params: Optional[dict] = None) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{API_BASE}/{path}", headers=_headers(), params=params or {})
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Health endpoint — registered as a custom route on FastMCP
# ---------------------------------------------------------------------------
@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": "singapore-weather", "tools": 5})


# ---------------------------------------------------------------------------
# Weather tools
# ---------------------------------------------------------------------------
@mcp.tool(
    description=(
        "Get the latest 2-hour weather forecast for Singapore areas. "
        "Optionally filter by area name (e.g. 'Tampines', 'Ang Mo Kio'). "
        "Updates every 30 minutes."
    )
)
async def get_two_hour_forecast(area: Optional[str] = None) -> str:
    data = await _get("two-hr-forecast")
    items = data.get("data", {}).get("items", [])
    if not items:
        return "No forecast data available."

    latest = items[0]
    valid = latest.get("valid_period", {})
    timestamp = _fmt_dt(latest.get("timestamp", ""))
    period = valid.get("text", f"{valid.get('start','')}–{valid.get('end','')}")
    forecasts = latest.get("forecasts", [])

    if area:
        forecasts = [f for f in forecasts if area.lower() in f["area"].lower()]
        if not forecasts:
            return f"No forecast found for '{area}'. Try a nearby area name."

    lines = [f"**2-Hour Forecast** (as of {timestamp}, valid {period})\n"]
    for f in forecasts:
        lines.append(f"  • {f['area']}: {f['forecast']}")
    return "\n".join(lines)


@mcp.tool(
    description=(
        "Get the 24-hour weather forecast for Singapore — general outlook, "
        "temperature range, humidity, and wind."
    )
)
async def get_twenty_four_hour_forecast() -> str:
    data = await _get("twenty-four-hr-forecast")
    records = data.get("data", {}).get("records", [])
    if not records:
        return "No 24-hour forecast data available."

    rec = records[0]
    general = rec.get("general", {})
    timestamp = _fmt_dt(rec.get("timestamp", rec.get("date", "")))
    temp = general.get("temperature", {})
    humidity = general.get("relativeHumidity", {})
    wind = general.get("wind", {})

    lines = [
        f"**24-Hour Forecast** (as of {timestamp})",
        f"Outlook: {general.get('forecast', {}).get('text', 'N/A')}",
        f"Temperature: {temp.get('low', '?')}–{temp.get('high', '?')}°C",
        f"Humidity: {humidity.get('low', '?')}–{humidity.get('high', '?')}%",
        f"Wind: {wind.get('direction', '?')} {wind.get('speed', {}).get('low', '?')}–{wind.get('speed', {}).get('high', '?')} km/h",
    ]
    for p in rec.get("periods", []):
        t = p.get("timePeriod", {})
        regions = ", ".join(f"{k}: {v}" for k, v in p.get("regions", {}).items())
        lines.append(f"  {t.get('start','')}–{t.get('end','')}: {regions}")
    return "\n".join(lines)


@mcp.tool(
    description=(
        "Get the 4-day weather forecast for Singapore. "
        "Use this for questions like 'will it rain this weekend?'"
    )
)
async def get_four_day_forecast() -> str:
    data = await _get("four-day-weather-forecast")
    records = data.get("data", {}).get("records", [])
    if not records:
        return "No 4-day forecast data available."

    rec = records[0]
    timestamp = _fmt_dt(rec.get("timestamp", rec.get("date", "")))
    lines = [f"**4-Day Forecast** (updated {timestamp})\n"]
    for day in rec.get("forecasts", []):
        forecast = day.get("forecast", {})
        temp = day.get("temperature", {})
        humidity = day.get("relativeHumidity", {})
        lines.append(
            f"  {day.get('date','')}: {forecast.get('summary', forecast.get('text','N/A'))} | "
            f"{temp.get('low','?')}–{temp.get('high','?')}°C | "
            f"Humidity {humidity.get('low','?')}–{humidity.get('high','?')}%"
        )
    return "\n".join(lines)


@mcp.tool(description="Get real-time air temperature (°C) from NEA weather stations across Singapore.")
async def get_realtime_temperature() -> str:
    data = await _get("air-temperature")
    stations = {s["id"]: s for s in data.get("data", {}).get("stations", [])}
    readings_list = data.get("data", {}).get("readings", [])
    if not readings_list:
        return "No temperature data available."
    latest = readings_list[0]
    timestamp = _fmt_dt(latest.get("timestamp", ""))
    lines = [f"**Real-time Temperature** (as of {timestamp})\n"]
    for r in latest.get("data", []):
        name = stations.get(r["stationId"], {}).get("name", r["stationId"])
        lines.append(f"  • {name}: {r['value']}°C")
    return "\n".join(lines)


@mcp.tool(description="Get real-time relative humidity (%) from NEA weather stations across Singapore.")
async def get_realtime_humidity() -> str:
    data = await _get("relative-humidity")
    stations = {s["id"]: s for s in data.get("data", {}).get("stations", [])}
    readings_list = data.get("data", {}).get("readings", [])
    if not readings_list:
        return "No humidity data available."
    latest = readings_list[0]
    timestamp = _fmt_dt(latest.get("timestamp", ""))
    lines = [f"**Real-time Humidity** (as of {timestamp})\n"]
    for r in latest.get("data", []):
        name = stations.get(r["stationId"], {}).get("name", r["stationId"])
        lines.append(f"  • {name}: {r['value']}%")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
