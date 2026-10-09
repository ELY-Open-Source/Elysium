#!/usr/bin/env bash
# Prove the MCP write tools reach the Python writer over HTTP, end to end.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
home="$(mktemp -d)"
port="${PORT:-8799}"
export ELY_EYE_HOME="$home"
export ELY_EYE_API="http://127.0.0.1:${port}"
# The server decides who may write; the MCP child inherits this and sends it on every mutation.
export ELY_EYE_AUTH_TOKEN="smoke-token"

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
wife_api=""
cleanup() {
  if [ -n "$api" ]; then kill "$api" 2>/dev/null || true; fi
  if [ -n "$wife_api" ]; then kill "$wife_api" 2>/dev/null || true; fi
  rm -rf "$home"
}
trap cleanup EXIT

# Refuse a busy port: the readiness probe only asks whether *something* answers, so a server left
# over from another run would be measured instead of ours and every assertion downstream would lie.
if curl -sf "http://127.0.0.1:${port}/api/status" >/dev/null 2>&1; then
  echo "FAIL: port ${port} already answers; stop that server or run with PORT=<free port>."
  exit 1
fi

"$python_bin" -m ely_eye.cli serve --port "$port" >"$home/api.log" 2>&1 &
api=$!

ready=0
for _ in $(seq 1 80); do
  if ! kill -0 "$api" 2>/dev/null; then
    echo "FAIL: the Ely-Eye API process exited before it was ready"
    cat "$home/api.log"
    exit 1
  fi
  if curl -sf "http://127.0.0.1:${port}/api/status" >/dev/null 2>&1; then ready=1; break; fi
  sleep 0.5
done
if [ "$ready" -ne 1 ]; then
  echo "FAIL: the Ely-Eye API did not start"
  cat "$home/api.log"
  exit 1
fi

# The gate, proved before anything else: a query needs nothing, a write needs the token.
status="$(curl -s -o "$home/refused.json" -w '%{http_code}' -X POST "http://127.0.0.1:${port}/api/memory" \
  -H 'content-type: application/json' -d '{"text":"a write with no token"}')"
if [ "$status" != "401" ]; then
  echo "FAIL: an untokened write returned HTTP $status, want 401"
  cat "$home/refused.json"
  exit 1
fi
status="$(curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:${port}/api/memory" \
  -H 'content-type: application/json' -H "Authorization: Bearer ${ELY_EYE_AUTH_TOKEN}" \
  -d '{"text":"a write with the token"}')"
if [ "$status" != "200" ]; then
  echo "FAIL: a tokened write returned HTTP $status, want 200"
  exit 1
fi

(cd "$root/ely-eye-mcp" && go build -o "$home/ely-eye-mcp" ./cmd/ely-eye-mcp)

# A second principal on the same SQLite file. The server, not the client, decides who a memory
# belongs to, so the only way to write as the wife is to ask a server whose principal is the wife.
wife_port=$((port + 1))
ELY_EYE_DEFAULT_HOLDER=wife "$python_bin" -m ely_eye.cli serve --port "$wife_port" >"$home/wife-api.log" 2>&1 &
wife_api=$!
ready=0
for _ in $(seq 1 80); do
  if curl -sf "http://127.0.0.1:${wife_port}/api/status" >/dev/null 2>&1; then ready=1; break; fi
  sleep 0.5
done
if [ "$ready" -ne 1 ]; then
  echo "FAIL: the wife's Ely-Eye API did not start"
  cat "$home/wife-api.log"
  exit 1
fi
secret="护照在书房第二个抽屉里"
curl -sf -X POST "http://127.0.0.1:${wife_port}/api/memory" -H 'content-type: application/json' \
  -H "Authorization: Bearer ${ELY_EYE_AUTH_TOKEN}" \
  -d "{\"text\":\"${secret}\",\"scenario\":\"home\"}" >/dev/null
curl -sf -X POST "http://127.0.0.1:${wife_port}/api/holders/wife" -H 'content-type: application/json' \
  -H "Authorization: Bearer ${ELY_EYE_AUTH_TOKEN}" \
  -d '{"name":"小美","kind":"person","knows_about":["护照"],"contact":{"channel":"signal","address":"+86-555"}}' >/dev/null

printf 'the pantry keeps flour\n' > "$home/pantry.txt"
uploaded="$(curl -sf -X POST "http://127.0.0.1:${port}/api/ingest/upload?cartridge_name=home" \
  -H "Authorization: Bearer ${ELY_EYE_AUTH_TOKEN}" \
  -F "files=@${home}/pantry.txt;type=text/plain")"
cartridge_id="$(printf '%s' "$uploaded" | "$python_bin" -c 'import json,sys; print(json.load(sys.stdin)["cartridge_id"])')"
if [ -z "$cartridge_id" ] || [ "$cartridge_id" = "None" ]; then
  echo "FAIL: the upload did not materialize a cartridge: $uploaded"
  exit 1
fi

"$python_bin" - "$home/ely-eye-mcp" "$cartridge_id" "$model_dir" "$secret" <<'PY'
import json
import pathlib
import subprocess
import sys

binary = sys.argv[1]
cartridge_id = sys.argv[2]
model_dir = pathlib.Path(sys.argv[3])
secret = sys.argv[4]
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
                 "mount_cartridge", "switch_cartridge", "unmount_cartridge", "append_to_cartridge",
                 "who_knows", "ask", "list_holders", "working_set", "memory_conflicts"):
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

# The transactive proof. The asker is this machine's principal; the wife's memory is private to
# her, so the directory may say she knows without showing what she knows.
holders = tool("list_holders", {})["holders"]
if not any(item["holder_id"] == "wife" for item in holders):
    raise SystemExit(f"FAIL: the registry does not list the wife: {holders}")

directory = tool("who_knows", {"query": "护照", "as_holder": "local"})["report"]
if directory["status"] != "found" or not directory["hits"]:
    raise SystemExit(f"FAIL: the directory found nobody who knows: {directory}")
top = directory["hits"][0]
if top["holder_id"] != "wife" or top["contact"].get("channel") != "signal":
    raise SystemExit(f"FAIL: the directory did not name the wife and how to reach her: {top}")
if not any("declared topics" in line for line in top["basis"]):
    raise SystemExit(f"FAIL: her declared topic did not raise the confidence: {top['basis']}")

referred = tool("ask", {"question": "护照在哪里", "as_holder": "local", "include_text": True})["answer"]
if referred["status"] != "referred" or referred["answered_by"] != "wife":
    raise SystemExit(f"FAIL: the question was not referred to the wife: {referred}")
if referred.get("answer"):
    raise SystemExit(f"FAIL: a private memory leaked into the referral: {referred['answer']}")
if secret in json.dumps(referred, ensure_ascii=False):
    raise SystemExit(f"FAIL: the referral carried the private text: {referred}")
if "wife" not in referred["asked"]:
    raise SystemExit(f"FAIL: the referral never asked the wife: {referred}")

mine = tool("ask", {"question": "pantry flour", "as_holder": "local", "include_text": True})["answer"]
if mine["status"] != "answered" or not mine["atom_ids"]:
    raise SystemExit(f"FAIL: the asker's own memory did not answer: {mine}")

nobody = tool("ask", {"question": "潜水镜", "as_holder": "local"})["answer"]
if nobody["status"] != "no_holder_knows" or nobody.get("answer"):
    raise SystemExit(f"FAIL: nobody knowing was reported as an answer: {nobody}")

# The tier proof. A session is what makes working memory a thing you can reload in
# order, and a disagreement is what makes an answer a choice rather than a coincidence.
session = "cooking-2026-10"
first = tool("remember", {"text": "the oven needs descaling", "session_id": session})["atom"]
second = tool("remember", {"text": "the pantry shelf holds flour", "session_id": session})["atom"]
if first["session_id"] != session:
    raise SystemExit(f"FAIL: the server dropped the session: {first}")
reloaded = tool("working_set", {"holder": "local", "session": session})["atoms"]
if [item["atom_id"] for item in reloaded] != [first["atom_id"], second["atom_id"]]:
    raise SystemExit(f"FAIL: the session did not reload in the order it was recorded: {reloaded}")
if tool("working_set", {"holder": "local", "session": "never-opened"})["atoms"]:
    raise SystemExit("FAIL: a session nobody recorded answered with somebody else's memories")

older = tool("remember", {"text": "the thermostat is set to 24 degrees", "scenario": "home"})["atom"]
newer = tool("remember", {"text": "the thermostat is set to 22 degrees", "scenario": "home"})["atom"]
clashes = tool("memory_conflicts", {"holder": "local"})["conflicts"]
if not any(item["older_atom_id"] == older["atom_id"] and item["newer_atom_id"] == newer["atom_id"]
           and item["older_value"] == "24" and item["newer_value"] == "22" for item in clashes):
    raise SystemExit(f"FAIL: the store never noticed that 24 degrees and 22 degrees cannot both hold: {clashes}")
settled = tool("search_atoms", {"query": "thermostat"})["hits"]
if any(hit["atom"]["atom_id"] == older["atom_id"] for hit in settled):
    raise SystemExit(f"FAIL: an unsettled conflict let the older side answer: {settled}")
if not any(hit["atom"]["atom_id"] == newer["atom_id"] for hit in settled):
    raise SystemExit(f"FAIL: the newer side of the conflict went missing: {settled}")

print("PASS: remember, supersede, search, forget, cartridge mounting, the transactive referral and the memory tiers work through MCP")
PY
