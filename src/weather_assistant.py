"""OpenAI + Xweather MCP assistant (lean, working)."""

from __future__ import annotations
import os, json
from typing import Any, Dict, List
from dotenv import load_dotenv
from openai import OpenAI
from .mcp_client import MCP

load_dotenv()

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
XW_ID = os.environ["XWEATHER_CLIENT_ID"]
XW_SECRET = os.environ["XWEATHER_CLIENT_SECRET"]
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

XW_MCP = "https://mcp.api.xweather.com/mcp"
XW_TOKEN = f"{XW_ID}_{XW_SECRET}"

def to_openai_tools(mcp_tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert MCP tool descriptions to OpenAI function-calling tools."""
    out: List[Dict[str, Any]] = []
    for t in mcp_tools:
        name = t.get("name")
        if not name:
            continue
        out.append({
            "type": "function",
            "function": {
                "name": name,
                "description": t.get("description", ""),
                "parameters": t.get("inputSchema", {"type": "object", "properties": {}, "required": []})
            }
        })
    return out

def extract_text(result: Dict[str, Any]) -> str:
    """Extract human-readable text from an MCP tool result."""
    content = result.get("content", [])
    parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
    return "\n".join([p for p in parts if p]) or json.dumps(result, indent=2)

def build_clients():
    """Try header auth first; fall back to query param auth."""
    # 1) header auth
    header_client = MCP(url=XW_MCP, headers={"Authorization": f"Bearer {XW_TOKEN}"})
    try:
        tools = header_client.list_tools()
        return header_client, tools, "header"
    except Exception:
        # 2) query param auth
        query_client = MCP(url=f"{XW_MCP}?api_key={XW_TOKEN}")
        tools = query_client.list_tools()
        return query_client, tools, "query"

class WeatherAssistant:
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.client = OpenAI(api_key=OPENAI_API_KEY)

        # Load MCP + tools once here (this is the __init__ I referred to)
        self.mcp, tools, mode = build_clients()
        self.oa_tools: List[Dict[str, Any]] = to_openai_tools(tools)
        if self.verbose:
            print(f"✓ Connected to Xweather MCP using {mode} auth; loaded {len(tools)} tools")

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg)

    def ask(self, question: str) -> str:
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": "You are a helpful weather assistant with access to Xweather tools."},
            {"role": "user", "content": question},
        ]

        # First model pass
        resp = self.client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            tools=self.oa_tools,
            tool_choice="auto",
        )
        msg = resp.choices[0].message
        messages.append(msg)

        # Handle tool calls, up to 2 rounds
        for _ in range(2):
            if not getattr(msg, "tool_calls", None):
                break

            for tc in msg.tool_calls:
                fname = tc.function.name
                try:
                    fargs = json.loads(tc.function.arguments)
                except json.JSONDecodeError as e:
                    self._log(f"Bad tool args: {e}")
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": f"Bad args: {e}"})
                    continue

                try:
                    result = self.mcp.call_tool(fname, fargs)
                    text = extract_text(result)
                    self._log(f"✓ {fname}")
                except Exception as e:
                    text = f"Error calling {fname}: {e}"
                    self._log(text)

                messages.append({"role": "tool", "tool_call_id": tc.id, "content": text})

            resp = self.client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=messages,
                tools=self.oa_tools,
            )
            msg = resp.choices[0].message
            messages.append(msg)

        return msg.content or "(no content)"


