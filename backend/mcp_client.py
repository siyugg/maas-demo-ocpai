"""
MCP client for the Singapore Weather MCP server.

Uses the Streamable HTTP transport with proper MCP protocol:
  1. POST /mcp  →  initialize   (gets Mcp-Session-Id header back)
  2. POST /mcp  →  notifications/initialized   (no response expected)
  3. POST /mcp  →  tools/list | tools/call  (normal JSON-RPC)

The session is created lazily and recreated on error.
The tools list is cached until a call fails.

The live call log (last 200 events) is pushed via asyncio.Queue to SSE
subscribers in /admin/mcp/log.
"""
import asyncio
import json
import time
import uuid
import logging
from collections import deque
from typing import Any, Optional

import httpx

from config import MCP_SERVER_URL

logger = logging.getLogger("mcp-client")

# ---------------------------------------------------------------------------
# Live call log — consumed by /admin/mcp/log SSE stream
# ---------------------------------------------------------------------------
_call_log: deque = deque(maxlen=200)
_call_log_subscribers: list = []


def _notify_subscribers(event: dict):
    dead = []
    for q in _call_log_subscribers:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        _call_log_subscribers.remove(q)


def get_call_log() -> list[dict]:
    return list(_call_log)


def subscribe_call_log() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _call_log_subscribers.append(q)
    return q


def unsubscribe_call_log(q: asyncio.Queue):
    try:
        _call_log_subscribers.remove(q)
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# MCP session (Streamable HTTP)
# ---------------------------------------------------------------------------
_session_id: Optional[str] = None
_session_lock = asyncio.Lock()
_tools_cache: Optional[list] = None

MCP_PROTO_VERSION = "2024-11-05"
_BASE_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


async def _get_session() -> str:
    """Return a live session ID, creating (or recreating) one if needed."""
    global _session_id
    async with _session_lock:
        if _session_id:
            return _session_id
        _session_id = await _open_session()
        return _session_id


async def _open_session() -> str:
    """Perform the MCP initialize / notifications/initialized handshake."""
    async with httpx.AsyncClient(timeout=10) as client:
        # Step 1 — initialize
        init_payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTO_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "maas-demo-bff", "version": "1.0"},
            },
        }
        resp = await client.post(
            f"{MCP_SERVER_URL}/mcp",
            json=init_payload,
            headers=_BASE_HEADERS,
        )
        resp.raise_for_status()
        session_id = resp.headers.get("mcp-session-id", "")
        if not session_id:
            # Some versions embed it in the body
            body = resp.json()
            session_id = body.get("result", {}).get("sessionId", str(uuid.uuid4()))

        logger.info("MCP session opened: %s", session_id)

        # Step 2 — notifications/initialized  (fire-and-forget, no response needed)
        notify_headers = {**_BASE_HEADERS, "Mcp-Session-Id": session_id}
        await client.post(
            f"{MCP_SERVER_URL}/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            headers=notify_headers,
        )

    return session_id


def _reset_session():
    global _session_id, _tools_cache
    _session_id = None
    _tools_cache = None
    logger.warning("MCP session reset")


async def _parse_mcp_response(resp: httpx.Response) -> Any:
    """
    FastMCP Streamable HTTP may respond with either:
      - application/json  →  direct JSON-RPC object
      - text/event-stream →  SSE stream; first 'message' event holds the response
    """
    content_type = resp.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        # Read all SSE lines and find the first data payload
        text = resp.text
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                raw = line[5:].strip()
                if raw:
                    return json.loads(raw)
        raise ValueError("No data event found in SSE response")
    else:
        return resp.json()


async def _mcp_call(method: str, params: dict) -> Any:
    """
    Generic JSON-RPC call over the Streamable HTTP session.
    Retries once after resetting the session on failure.
    Handles both direct JSON and SSE-wrapped responses from FastMCP.
    """
    for attempt in range(2):
        session_id = await _get_session()
        headers = {**_BASE_HEADERS, "Mcp-Session-Id": session_id}
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params,
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{MCP_SERVER_URL}/mcp",
                    json=payload,
                    headers=headers,
                )
                if resp.status_code in (400, 401, 404) and attempt == 0:
                    _reset_session()
                    continue
                resp.raise_for_status()
                return await _parse_mcp_response(resp)
        except httpx.HTTPStatusError as exc:
            if attempt == 0:
                _reset_session()
                continue
            raise
    raise RuntimeError(f"MCP call '{method}' failed after retry")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
async def get_tools() -> list[dict]:
    """Fetch the MCP tools list (cached until session reset)."""
    global _tools_cache
    if _tools_cache is not None:
        return _tools_cache
    data = await _mcp_call("tools/list", {})
    _tools_cache = data.get("result", {}).get("tools", [])
    logger.info("MCP tools loaded: %s", [t["name"] for t in _tools_cache])
    return _tools_cache


async def call_tool(tool_name: str, arguments: dict[str, Any]) -> Any:
    """Call a named MCP tool and record the event in the live call log."""
    call_id = str(uuid.uuid4())[:8]
    start = time.perf_counter()
    error = None
    result_content = None

    try:
        data = await _mcp_call("tools/call", {"name": tool_name, "arguments": arguments})
        content = data.get("result", {}).get("content", [])
        result_content = " ".join(
            c.get("text", "") for c in content if c.get("type") == "text"
        )
    except Exception as exc:
        error = str(exc)
        logger.error("MCP tool call failed: %s — %s", tool_name, exc)
        # Reset session so next call re-initializes
        _reset_session()

    elapsed_ms = round((time.perf_counter() - start) * 1000)

    event = {
        "id": call_id,
        "timestamp": time.strftime("%H:%M:%S"),
        "tool": tool_name,
        "args": arguments,
        "latency_ms": elapsed_ms,
        "success": error is None,
        "error": error,
        "preview": (result_content or "")[:120],
    }
    _call_log.appendleft(event)
    _notify_subscribers(event)

    if error:
        raise RuntimeError(f"MCP tool '{tool_name}' failed: {error}")
    return result_content


async def get_mcp_health() -> dict:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{MCP_SERVER_URL}/health")
            resp.raise_for_status()
            return {"healthy": True, **resp.json()}
    except Exception as exc:
        return {"healthy": False, "error": str(exc)}


def tools_as_openai_functions(tools: list[dict]) -> list[dict]:
    """Convert MCP tools list to OpenAI function-calling format."""
    result = []
    for t in tools:
        result.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("inputSchema", {"type": "object", "properties": {}}),
            },
        })
    return result
