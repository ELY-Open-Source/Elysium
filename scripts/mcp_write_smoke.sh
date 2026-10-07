#!/usr/bin/env bash
# Prove the MCP write tools reach the Python writer over HTTP, end to end.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
home="$(mktemp -d)"
port="${PORT:-8799}"
export ELY_EYE_HOME="$home"
export ELY_EYE_API="http://127.0.0.1:${port}"

python_bin="$root/.venv/bin/python"
[ -x "$python_bin" ] || python_bin="python3"

# A model snapshot the KV fingerprint can read: without it every mount is refused as
# unverifiable, which is the behaviour, but the smoke test also needs a mount to succeed.
model_dir="$home/model"
mkdir -p "$model_dir"
cat > "$model_dir/config.json" <<'JSON'
{"model_type": "qwen3_5", "max_position_embeddings": 262144, "partial_rotary_factor": 0.25,
 "rope_parameters": {"rope_type": "yarn", "factor": 4.0, "mrope_section": [11, 11, 10]},
 "chat_template": "{% for message in messages %}{{ message['content'] }}{% endfor %}"}
JSON
printf '{"version": "1.0"}' > "$model_dir/tokenizer.json"
printf '{"metadata": {}, "weight_map": {"model-00001.safetensors": "0"}}' > "$model_dir/model.safetensors.index.json"
export ELY_EYE_MODEL_DIR="$model_dir"

api=""
cleanup() {
  if [ -n "$api" ]; then kill "$api" 2>/dev/null || true; fi
  rm -rf "$home"
}
trap cleanup EXIT

"$python_bin" -m ely_eye.cli serve --port "$port" >"$home/api.log" 2>&1 &
api=$!

ready=0
for _ in $(seq 1 80); do
  if curl -sf "http://127.0.0.1:${port}/api/status" >/dev/null 2>&1; then ready=1; break; fi
  sleep 0.5
done
if [ "$ready" -ne 1 ]; then
  echo "FAIL: the Ely-Eye API did not start"
  cat "$home/api.log"
  exit 1
fi

(cd "$root/ely-eye-mcp" && go build -o "$home/ely-eye-mcp" ./cmd/ely-eye-mcp)

printf 'the pantry keeps flour\n' > "$home/pantry.txt"
uploaded="$(curl -sf -X POST "http://127.0.0.1:${port}/api/ingest/upload?cartridge_name=home" \
  -F "files=@${home}/pantry.txt;type=text/plain")"
cartridge_id="$(printf '%s' "$uploaded" | "$python_bin" -c 'import json,sys; print(json.load(sys.stdin)["cartridge_id"])')"
if [ -z "$cartridge_id" ] || [ "$cartridge_id" = "None" ]; then
  echo "FAIL: the upload did not materialize a cartridge: $uploaded"
  exit 1
fi

"$python_bin" - "$home/ely-eye-mcp" "$cartridge_id" "$model_dir" <<'PY'
import json
import pathlib
import subprocess
import sys

binary = sys.argv[1]
cartridge_id = sys.argv[2]
model_dir = pathlib.Path(sys.argv[3])
proc = subprocess.Popen(
    [binary, "server"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,
    text=True,
)


def send(message):
    proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
    proc.stdin.flush()


def call(id_, method, params):
    send({"jsonrpc": "2.0", "id": id_, "method": method, "params": params})
    while True:
        line = proc.stdout.readline()
        if not line:
            raise SystemExit(f"FAIL: the MCP server closed the pipe at request {id_}")
        answer = json.loads(line)
        if answer.get("id") == id_:
            if "error" in answer:
                raise SystemExit(f"FAIL: {method} returned {answer['error']}")
            return answer["result"]


def tool(name, arguments):
    result = call(3, "tools/call", {"name": name, "arguments": arguments})
    if result.get("isError"):
        raise SystemExit(f"FAIL: {name} returned an error: {result['content']}")
    return result["structuredContent"]


call(1, "initialize", {
    "protocolVersion": "2025-06-18",
    "capabilities": {},
    "clientInfo": {"name": "ely-eye-smoke", "version": "0"},
})
send({"jsonrpc": "2.0", "method": "notifications/initialized"})

names = [item["name"] for item in call(2, "tools/list", {})["tools"]]
for required in ("remember", "supersede_memory", "forget_memory", "mounted_cartridges",
                 "mount_cartridge", "switch_cartridge", "unmount_cartridge", "append_to_cartridge"):
    if required not in names:
        raise SystemExit(f"FAIL: {required} is not registered; tools are {names}")

statement = "keys are in the hall drawer"
remembered = tool("remember", {"text": statement, "scenario": "home"})["atom"]
if not remembered["holder_id"]:
    raise SystemExit(f"FAIL: the server stamped no holder: {remembered}")
atom_id = remembered["atom_id"]

hits = tool("search_atoms", {"query": statement})["hits"]
if not hits or hits[0]["atom"]["atom_id"] != atom_id:
    raise SystemExit(f"FAIL: the new memory is not retrievable: {hits}")
if hits[0]["atom"].get("scenario") != "home":
    raise SystemExit(f"FAIL: the search hit lost the scenario: {hits[0]['atom']}")

chinese = tool("remember", {"text": "我们的钥匙放在玄关抽屉里", "scenario": "home"})["atom"]
short = tool("search_atoms", {"query": "钥匙"})["hits"]
if not any(hit["atom"]["atom_id"] == chinese["atom_id"] for hit in short):
    raise SystemExit(f"FAIL: a two-character Chinese query missed the memory written in Chinese: {short}")
if tool("search_atoms", {"query": "keys", "scenario": "travel"})["hits"]:
    raise SystemExit("FAIL: the scenario filter let another scenario answer")

replacement = "keys are on the coffee table"
newer = tool("supersede_memory", {"atom_id": atom_id, "text": replacement})["atom"]
if newer["supersedes"] != [atom_id]:
    raise SystemExit(f"FAIL: the replacement does not point back: {newer}")

after = tool("search_atoms", {"query": statement})["hits"]
if any(hit["atom"]["atom_id"] == atom_id for hit in after):
    raise SystemExit(f"FAIL: the superseded memory is still retrievable: {after}")

report = tool("forget_memory", {"atom_id": atom_id})["report"]
if report["atoms_deleted"] != 1:
    raise SystemExit(f"FAIL: forget deleted {report['atoms_deleted']} atoms, want 1")
gone = call(3, "tools/call", {"name": "fetch_atom", "arguments": {"atom_id": atom_id}})
if not gone.get("isError") or "not found" not in gone["content"][0]["text"]:
    raise SystemExit(f"FAIL: the forgotten memory is still readable: {gone}")

state = tool("mounted_cartridges", {})["state"]
if state["mounted"] or state["scoped"]:
    raise SystemExit(f"FAIL: a fresh store reports a scope: {state}")

outside = tool("remember", {"text": "the spare key hides in the garage", "scenario": "work"})["atom"]
manifest = tool("mount_cartridge", {"cartridge_id": cartridge_id})["manifest"]
if manifest["cartridge_id"] != cartridge_id or not manifest.get("dna"):
    raise SystemExit(f"FAIL: mount returned the wrong header: {manifest}")
state = tool("mounted_cartridges", {})["state"]
if not state["scoped"] or state["mounted"] != [cartridge_id]:
    raise SystemExit(f"FAIL: the mount did not take effect: {state}")
if tool("search_atoms", {"query": "garage"})["hits"]:
    raise SystemExit("FAIL: a mounted cartridge let a memory outside it answer")

grown = tool("append_to_cartridge", {"cartridge_id": cartridge_id, "atom_ids": [outside["atom_id"]]})["manifest"]
if grown["dna"] == manifest["dna"]:
    raise SystemExit("FAIL: append rewrote nothing; the DNA is unchanged")
if not any(hit["atom"]["atom_id"] == outside["atom_id"] for hit in tool("search_atoms", {"query": "garage"})["hits"]):
    raise SystemExit("FAIL: an appended memory is still not reachable")

tool("unmount_cartridge", {"cartridge_id": cartridge_id})
if tool("mounted_cartridges", {})["state"]["scoped"]:
    raise SystemExit("FAIL: unmount left the store scoped")

(model_dir / "config.json").write_text(json.dumps({
    "model_type": "qwen3_5",
    "max_position_embeddings": 262144,
    "partial_rotary_factor": 0.25,
    "rope_parameters": {"rope_type": "yarn", "factor": 2.0},
    "chat_template": "{% for message in messages %}{{ message['content'] }}{% endfor %}",
}), encoding="utf-8")
refused = call(3, "tools/call", {"name": "mount_cartridge", "arguments": {"cartridge_id": cartridge_id}})
if not refused.get("isError") or "rope" not in refused["content"][0]["text"]:
    raise SystemExit(f"FAIL: a cartridge built for RoPE factor 4.0 mounted on a factor 2.0 machine: {refused}")

print("PASS: remember, supersede, search, forget and cartridge mounting work through MCP")
PY
