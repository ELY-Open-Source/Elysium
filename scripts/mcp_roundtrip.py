"""Drive an installed elysian-mcp over stdio as any MCP client does: write one memory, read it back.

Standard library only, so the Python that uv installed with Elysian can run it on a machine that had none.
Run: python scripts/mcp_roundtrip.py <path to elysian-mcp> <stderr log>
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import IO, Any


class Client:
    def __init__(self, binary: str, errors: IO[str]) -> None:
        self.proc = subprocess.Popen([binary, "server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors, text=True, encoding="utf-8")
        self.errors = errors
        self.stdin: IO[str] = self.proc.stdin  # type: ignore[assignment]
        self.stdout: IO[str] = self.proc.stdout  # type: ignore[assignment]

    def send(self, message: dict[str, Any]) -> None:
        self.stdin.write(json.dumps(message) + "\n")
        self.stdin.flush()

    def call(self, id_: int, method: str, params: dict[str, Any]) -> Any:
        self.send({"jsonrpc": "2.0", "id": id_, "method": method, "params": params})
        while True:
            line = self.stdout.readline()
            if not line:
                self.errors.flush()
                raise SystemExit(f"FAIL: the MCP server closed the pipe at {method}; see {self.errors.name}")
            answer = json.loads(line)
            if answer.get("id") == id_:
                if "error" in answer:
                    raise SystemExit(f"FAIL: {method} returned {answer['error']}")
                return answer["result"]

    def tool(self, id_: int, name: str, arguments: dict[str, Any]) -> Any:
        result = self.call(id_, "tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise SystemExit(f"FAIL: {name} returned an error: {result['content']}")
        return result["structuredContent"]


def main() -> int:
    binary, log = sys.argv[1], sys.argv[2]
    with open(log, "w", encoding="utf-8") as errors:
        client = Client(binary, errors)
        client.call(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "roundtrip", "version": "0"}})
        client.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        atom = client.tool(2, "remember", {"text": "the spare key hangs behind the calendar", "scenario": "home"})["atom"]
        hits = client.tool(3, "search_atoms", {"query": "spare key calendar"})["hits"]
        if not hits or hits[0]["atom"]["atom_id"] != atom["atom_id"]:
            raise SystemExit(f"FAIL: the memory written through MCP is not found: {hits}")
        client.stdin.close()
        client.proc.wait(timeout=10)
    print(f"PASS: a memory went in through {binary} and came back, held by {atom['holder_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
