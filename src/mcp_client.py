"""Minimal Xweather MCP JSON-RPC client (HTTP) with JSON + SSE support."""

from __future__ import annotations
import json
from typing import Any, Dict, List, Optional
import httpx

class MCPError(RuntimeError):
    pass

class MCP:
    def __init__(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 30.0,
    ):
        self.url = url
        self._id = 0
        self.http = httpx.Client(timeout=timeout)
        self.extra_headers = headers or {}

    def _next_id(self) -> int:
        self._id += 1
        return self._id



    def list_tools(self) -> List[Dict[str, Any]]:
        res = self._rpc("tools/list")
        tools = res.get("tools", [])
        if not isinstance(tools, list):
            raise MCPError(f"Invalid tools/list shape:\n{json.dumps(res, indent=2)[:800]}")
        return tools

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return self._rpc("tools/call", {"name": name, "arguments": arguments})



    def _rpc(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = {"jsonrpc": "2.0", "id": self._next_id(), "method": method, "params": params or {}}
        try:
            r = self.http.post(
                self.url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    # Server requires accepting both JSON and SSE:
                    "Accept": "application/json, text/event-stream",
                    "Connection": "keep-alive",
                    **self.extra_headers,
                },
            )
        except httpx.HTTPError as e:
            raise MCPError(f"Network error contacting MCP: {e}") from e

        if r.status_code < 200 or r.status_code >= 300:
            preview = r.text[:600] if r.text else "<empty body>"
            raise MCPError(f"HTTP {r.status_code} from MCP; body preview:\n{preview}")

        ctype = (r.headers.get("Content-Type") or "").lower()

        if "application/json" in ctype:
            # Normal JSON path
            try:
                doc = r.json()
            except json.JSONDecodeError as e:
                raise MCPError(f"Invalid JSON from MCP: {e}\nBody preview:\n{r.text[:600]}")
            return self._unwrap_jsonrpc(doc)

        if "text/event-stream" in ctype:
            # SSE path: extract the latest data: payload and parse as JSON
            try:
                doc = self._parse_sse_to_json(r)
            except MCPError:
                raise
            except Exception as e:
                raise MCPError(f"Failed to parse SSE: {e}\nBody preview:\n{r.text[:600]}")
            return self._unwrap_jsonrpc(doc)

        # Fallback: attempt JSON anyway, else show preview
        try:
            doc = r.json()
            return self._unwrap_jsonrpc(doc)
        except Exception:
            preview = r.text[:600] if r.text else "<empty body>"
            raise MCPError(f"Unexpected Content-Type '{ctype}'. Body preview:\n{preview}")

    @staticmethod
    def _unwrap_jsonrpc(doc: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(doc, dict) or doc.get("jsonrpc") != "2.0":
            raise MCPError(f"Invalid JSON-RPC envelope:\n{json.dumps(doc, indent=2)[:800]}")
        if doc.get("error"):
            err = doc["error"]
            raise MCPError(f"MCP error {err.get('code')}: {err.get('message')}")
        result = doc.get("result")
        if not isinstance(result, dict):
            raise MCPError("Missing/invalid result in JSON-RPC response")
        return result

    @staticmethod
    def _parse_sse_to_json(resp: httpx.Response) -> Dict[str, Any]:
        """
        Parse a text/event-stream response and return the last JSON object
        seen in a 'data:' field. Works with buffered responses (httpx default).
        """
        text = resp.text.splitlines()
        data_buf: list[str] = []
        last_data: Optional[str] = None

        for line in text:
            # Ignore comments/heartbeats starting with ':'
            if line.startswith(":"):
                continue
            if line.startswith("data:"):
                # Collect data lines; strip the leading 'data:' and any one space
                payload = line[5:].lstrip()
                data_buf.append(payload)
            elif line.strip() == "":
                # Blank line = event boundary
                if data_buf:
                    last_data = "\n".join(data_buf)
                    data_buf = []

        # Capture any trailing data that wasn't followed by a blank line
        if data_buf:
            last_data = "\n".join(data_buf)

        if not last_data:
            raise MCPError("SSE response contained no 'data:' payload")

        try:
            return json.loads(last_data)
        except json.JSONDecodeError as e:
            raise MCPError(f"SSE 'data' not valid JSON: {e}")
