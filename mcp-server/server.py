"""
MCP Server for Singapore weather + LTA transport datasets via data.gov.sg.
Uses FastMCP Streamable HTTP transport with native lifecycle management.
"""
import csv
import io
import os
import asyncio
import logging
import time
from datetime import datetime
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("mcp-server")

API_BASE = "https://api-open.data.gov.sg/v2/real-time/api"
API_KEY = os.getenv("DATA_GOV_SG_API_KEY", "")
PUBLIC_API_BASE = "https://api-open.data.gov.sg/v1/public/api"
COLLECTION_API_BASE = "https://api-production.data.gov.sg/v2/public/api"

# data.gov.sg collection 379 datasets
LTA_COLLECTION_ID = "379"
LTA_DATASET_TRAFFIC_VOLUME = "d_3136f317a1f282a33fe7a2f6a907c047"
LTA_DATASET_PEAK_SPEED = "d_26f6afadf2f86b2004f9a1e28f5564cc"

_dataset_cache: dict[str, tuple[float, list[dict]]] = {}
DATASET_CACHE_TTL = 6 * 60 * 60  # 6 hours

mcp = FastMCP(
    name="singapore-insights",
    host="0.0.0.0",
    port=8000,
    instructions=(
        "You have access to Singapore live weather and LTA road traffic datasets from data.gov.sg. "
        "Use the tools for factual answers and always cite time period or latest year."
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


async def _get_collection_metadata(collection_id: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{COLLECTION_API_BASE}/collections/{collection_id}/metadata")
        resp.raise_for_status()
        return resp.json()


def _num(x) -> float:
    if x is None:
        return 0.0
    s = str(x).strip().replace(",", "")
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


async def _download_dataset_rows(dataset_id: str) -> list[dict]:
    """
    Download CSV dataset via data.gov.sg two-step API:
      initiate-download -> poll-download -> fetch signed CSV URL.
    Cached to avoid hitting 5 req/min public quota.
    """
    now = time.time()
    cached = _dataset_cache.get(dataset_id)
    if cached and (now - cached[0]) < DATASET_CACHE_TTL:
        return cached[1]

    async with httpx.AsyncClient(timeout=20) as client:
        init = await client.get(f"{PUBLIC_API_BASE}/datasets/{dataset_id}/initiate-download")
        init.raise_for_status()

        csv_url = None
        for _ in range(6):
            poll = await client.get(f"{PUBLIC_API_BASE}/datasets/{dataset_id}/poll-download")
            poll.raise_for_status()
            body = poll.json()
            status = body.get("data", {}).get("status", "")
            if status == "DOWNLOAD_SUCCESS":
                csv_url = body.get("data", {}).get("url")
                break
            await asyncio.sleep(0.5)

        if not csv_url:
            raise RuntimeError(f"Dataset {dataset_id}: download URL not ready after polling.")

        csv_resp = await client.get(csv_url)
        csv_resp.raise_for_status()
        text = csv_resp.text

    reader = csv.DictReader(io.StringIO(text))
    rows = [dict(r) for r in reader]
    _dataset_cache[dataset_id] = (now, rows)
    return rows


# ---------------------------------------------------------------------------
# Health endpoint — registered as a custom route on FastMCP
# ---------------------------------------------------------------------------
@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": "singapore-insights", "tools": 12})


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


@mcp.tool(description="Get real-time rainfall (mm) from NEA weather stations across Singapore.")
async def get_realtime_rainfall() -> str:
    data = await _get("rainfall")
    stations = {s["id"]: s for s in data.get("data", {}).get("stations", [])}
    readings_list = data.get("data", {}).get("readings", [])
    if not readings_list:
        return "No rainfall data available."
    latest = readings_list[0]
    timestamp = _fmt_dt(latest.get("timestamp", ""))
    lines = [f"**Real-time Rainfall** (as of {timestamp})\n"]
    for r in latest.get("data", []):
        name = stations.get(r["stationId"], {}).get("name", r["stationId"])
        lines.append(f"  • {name}: {r['value']} mm")
    return "\n".join(lines)


@mcp.tool(description="Get real-time wind direction (degrees) from NEA weather stations across Singapore.")
async def get_realtime_wind_direction() -> str:
    data = await _get("wind-direction")
    stations = {s["id"]: s for s in data.get("data", {}).get("stations", [])}
    readings_list = data.get("data", {}).get("readings", [])
    if not readings_list:
        return "No wind direction data available."
    latest = readings_list[0]
    timestamp = _fmt_dt(latest.get("timestamp", ""))
    lines = [f"**Real-time Wind Direction** (as of {timestamp})\n"]
    for r in latest.get("data", []):
        name = stations.get(r["stationId"], {}).get("name", r["stationId"])
        lines.append(f"  • {name}: {r['value']}°")
    return "\n".join(lines)


@mcp.tool(description="Get real-time wind speed (km/h) from NEA weather stations across Singapore.")
async def get_realtime_wind_speed() -> str:
    data = await _get("wind-speed")
    stations = {s["id"]: s for s in data.get("data", {}).get("stations", [])}
    readings_list = data.get("data", {}).get("readings", [])
    if not readings_list:
        return "No wind speed data available."
    latest = readings_list[0]
    timestamp = _fmt_dt(latest.get("timestamp", ""))
    lines = [f"**Real-time Wind Speed** (as of {timestamp})\n"]
    for r in latest.get("data", []):
        name = stations.get(r["stationId"], {}).get("name", r["stationId"])
        lines.append(f"  • {name}: {r['value']} km/h")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LTA road traffic tools (Collection 379)
# ---------------------------------------------------------------------------
@mcp.tool(description="Get metadata overview for LTA road traffic collection 379 on data.gov.sg.")
async def get_lta_transport_collection_overview() -> str:
    data = await _get_collection_metadata(LTA_COLLECTION_ID)
    meta = data.get("data", {}).get("collectionMetadata", {})
    if not meta:
        return "No collection metadata available."

    return (
        f"**LTA Collection {LTA_COLLECTION_ID}: {meta.get('name', 'N/A')}**\n"
        f"Description: {meta.get('description', 'N/A')}\n"
        f"Managed by: {meta.get('managedBy', 'N/A')}\n"
        f"Coverage: {meta.get('coverageStart', 'N/A')} to {meta.get('coverageEnd', 'N/A')}\n"
        f"Last updated: {meta.get('lastUpdatedAt', 'N/A')}\n"
        f"Datasets: {', '.join(meta.get('childDatasets', []))}"
    )


@mcp.tool(description="Get annual average daily traffic volume entering city from LTA dataset.")
async def get_lta_city_traffic_volume(year_start: Optional[int] = None, year_end: Optional[int] = None) -> str:
    rows = await _download_dataset_rows(LTA_DATASET_TRAFFIC_VOLUME)
    parsed = []
    for r in rows:
        y = int(_num(r.get("year")))
        v = _num(r.get("ave_daily_traffic_volume_entering_city"))
        parsed.append((y, v))
    parsed.sort(key=lambda x: x[0])

    if year_start is not None:
        parsed = [p for p in parsed if p[0] >= year_start]
    if year_end is not None:
        parsed = [p for p in parsed if p[0] <= year_end]
    if not parsed:
        return "No traffic volume data found for the requested year range."

    latest_year, latest_val = parsed[-1]
    first_year, first_val = parsed[0]
    change_pct = ((latest_val - first_val) / first_val * 100) if first_val else 0

    tail = parsed[-6:]
    lines = [
        "**LTA Average Daily Traffic Volume Entering City**",
        f"Range: {parsed[0][0]}–{parsed[-1][0]} | Latest: {latest_year} = {latest_val:,.0f}",
        f"Change from {first_year} to {latest_year}: {change_pct:+.1f}%",
        "Recent years:",
    ]
    lines.extend([f"  • {y}: {v:,.0f}" for y, v in tail])
    return "\n".join(lines)


@mcp.tool(description="Get annual average peak-hour speed for expressways and arterial roads from LTA dataset.")
async def get_lta_peak_hour_speed(year_start: Optional[int] = None, year_end: Optional[int] = None) -> str:
    rows = await _download_dataset_rows(LTA_DATASET_PEAK_SPEED)
    parsed = []
    for r in rows:
        y = int(_num(r.get("year")))
        ex = _num(r.get("ave_speed_expressway"))
        ar = _num(r.get("ave_speed_arterial_roads"))
        parsed.append((y, ex, ar))
    parsed.sort(key=lambda x: x[0])

    if year_start is not None:
        parsed = [p for p in parsed if p[0] >= year_start]
    if year_end is not None:
        parsed = [p for p in parsed if p[0] <= year_end]
    if not parsed:
        return "No peak-hour speed data found for the requested year range."

    latest = parsed[-1]
    tail = parsed[-6:]
    lines = [
        "**LTA Peak-Hour Average Speed**",
        f"Range: {parsed[0][0]}–{parsed[-1][0]}",
        f"Latest ({latest[0]}): Expressway {latest[1]:.1f} km/h, Arterial roads {latest[2]:.1f} km/h",
        "Recent years:",
    ]
    lines.extend([f"  • {y}: Expressway {ex:.1f} km/h | Arterial {ar:.1f} km/h" for y, ex, ar in tail])
    return "\n".join(lines)


@mcp.tool(description="Get a concise LTA transport summary combining traffic volume and peak-hour speed trends.")
async def get_lta_peak_hour_summary(compare_years: int = 5) -> str:
    vol_rows = await _download_dataset_rows(LTA_DATASET_TRAFFIC_VOLUME)
    speed_rows = await _download_dataset_rows(LTA_DATASET_PEAK_SPEED)

    vol = sorted(
        [(int(_num(r.get("year"))), _num(r.get("ave_daily_traffic_volume_entering_city"))) for r in vol_rows],
        key=lambda x: x[0],
    )
    spd = sorted(
        [
            (
                int(_num(r.get("year"))),
                _num(r.get("ave_speed_expressway")),
                _num(r.get("ave_speed_arterial_roads")),
            )
            for r in speed_rows
        ],
        key=lambda x: x[0],
    )
    if not vol or not spd:
        return "LTA transport datasets are unavailable right now."

    latest_vol_year, latest_vol = vol[-1]
    latest_spd_year, latest_ex, latest_ar = spd[-1]

    vol_ref_idx = max(0, len(vol) - 1 - max(1, compare_years))
    spd_ref_idx = max(0, len(spd) - 1 - max(1, compare_years))
    ref_vol_year, ref_vol = vol[vol_ref_idx]
    ref_spd_year, ref_ex, ref_ar = spd[spd_ref_idx]

    vol_change = ((latest_vol - ref_vol) / ref_vol * 100) if ref_vol else 0
    ex_change = latest_ex - ref_ex
    ar_change = latest_ar - ref_ar

    return (
        "**LTA Peak-Hour Transport Summary**\n"
        f"Latest traffic volume entering city ({latest_vol_year}): {latest_vol:,.0f}\n"
        f"Traffic volume change since {ref_vol_year}: {vol_change:+.1f}%\n"
        f"Latest average speed ({latest_spd_year}): Expressway {latest_ex:.1f} km/h, Arterial {latest_ar:.1f} km/h\n"
        f"Speed change since {ref_spd_year}: Expressway {ex_change:+.1f} km/h, Arterial {ar_change:+.1f} km/h\n"
        "Note: This dataset is annual historical data, not minute-by-minute live traffic."
    )


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
