"""Download pinned corpus files and record a frozen manifest.

Upstream LFS pointers are unreliable: some declare a wrong size, some name an
oid that does not match the served blob. Files are hashed as served, every
pointer discrepancy is recorded in the manifest, and the corpus builder drops
documents whose annotations reference pages the served file lacks.
"""

import argparse
import hashlib
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from bench.corpus_sources import GIT_REPOS, SOURCES
from bench.sets_common import parse_json_line

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "bench" / "corpus"
MANIFEST = CORPUS / "manifest.jsonl"
UA = {"User-Agent": "elysium-bench"}
OPENER = urllib.request.build_opener(urllib.request.HTTPSHandler())


def http_get(url: str) -> tuple[bytes, dict[str, str]]:
    if urllib.parse.urlsplit(url).scheme != "https" or urllib.parse.urlsplit(url).netloc != "huggingface.co":
        raise SystemExit(f"refusing non-HF url: {url}")
    try:
        resp = OPENER.open(urllib.request.Request(url, headers=UA), timeout=300)
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"HTTP {exc.code} {url}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"network {exc.reason} {url}") from exc
    with resp:
        return resp.read(), dict(resp.headers)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def api(url: str) -> tuple[list, dict[str, str]]:
    body, headers = http_get(url)
    try:
        payload = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SystemExit(f"bad JSON from {url}: {exc}") from exc
    return payload, headers


def next_link(headers: dict[str, str]) -> str | None:
    header = headers.get("Link")
    if not header:
        return None
    for part in header.split(","):
        head, _, rel = part.partition(">")
        if 'rel="next"' in rel:
            return head.strip().strip("<>")
    return None


def list_files(dataset: str, revision: str) -> list[dict]:
    out: list[dict] = []
    url: str | None = f"https://huggingface.co/api/datasets/{dataset}/tree/{revision}?recursive=true"
    while url:
        batch, headers = api(url)
        out += [f for f in batch if f["type"] == "file"]
        url = next_link(headers)
    return out


def file_digest(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
            size += len(block)
    return size, digest.hexdigest()


def download_to(url: str, dest: Path) -> tuple[int, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    digest = hashlib.sha256()
    size = 0
    try:
        resp = OPENER.open(urllib.request.Request(url, headers=UA), timeout=600)
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"HTTP {exc.code} {url}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"network {exc.reason} {url}") from exc
    try:
        with resp, tmp.open("wb") as handle:
            for block in iter(lambda: resp.read(1 << 20), b""):
                digest.update(block)
                size += len(block)
                handle.write(block)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise SystemExit(f"write failed for {url}: {exc}") from exc
    tmp.replace(dest)
    return size, digest.hexdigest()


def check_path(path: str) -> str:
    if path.startswith("/") or ".." in Path(path).parts:
        raise SystemExit(f"unsafe corpus path: {path}")
    return path


def pointer_for(dataset: str, revision: str, path: str) -> tuple[str | None, int | None]:
    raw, _ = http_get(f"https://huggingface.co/datasets/{dataset}/raw/{revision}/{path}")
    if not raw.startswith(b"version https://git-lfs"):
        return None, None
    fields = dict(
        line.decode().split(" ", 1) for line in raw.splitlines() if b" " in line
    )
    oid = fields.get("oid", "").removeprefix("sha256:") or None
    if "size" not in fields:
        return oid, None
    try:
        size = int(fields["size"])
    except ValueError as exc:
        raise SystemExit(f"bad LFS pointer size for {dataset}/{path}: {fields['size']!r}") from exc
    return oid, size


def fetch_file(dataset: str, revision: str, path: str) -> dict:
    check_path(path)
    oid, declared = pointer_for(dataset, revision, path)
    url = f"https://huggingface.co/datasets/{dataset}/resolve/{revision}/{path}"
    target = CORPUS / dataset / path
    if target.exists() and target.stat().st_size > 0:
        size, actual = file_digest(target)
        fresh = False
    else:
        size, actual = download_to(url, target)
        fresh = True
    return {
        "dataset": dataset,
        "revision": revision,
        "path": path,
        "url": url,
        "bytes": size,
        "sha256": actual,
        "lfs_pointer_oid": oid,
        "lfs_pointer_bytes": declared,
        "oid_match": oid is None or actual == oid,
        "newly_downloaded": fresh,
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def fetch_git(repo: dict) -> dict:
    name = repo["repo"].rsplit("/", 1)[-1]
    target = CORPUS / "_git" / name
    fresh = not target.exists()
    if fresh:
        subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", repo["ref"], repo["repo"], str(target)],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    head = subprocess.run(
        ["git", "-C", str(target), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    pinned = repo.get("sha")
    if pinned and head != pinned:
        raise SystemExit(
            f"{repo['repo']}: checked-out HEAD {head} != pinned sha {pinned}; "
            "re-fetch at the pinned commit or re-pin deliberately"
        )
    tracked = [f for f in target.rglob("*") if f.is_file() and ".git" not in f.parts]
    return {
        "dataset": repo["repo"],
        "revision": head,
        "path": f"_git/{name}",
        "url": f"{repo['repo']}/archive/{head}.tar.gz",
        "bytes": sum(f.stat().st_size for f in tracked),
        "sha256": head,
        "lfs_pointer_oid": None,
        "lfs_pointer_bytes": None,
        "oid_match": True,
        "newly_downloaded": fresh,
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "file_count": len(tracked),
    }


def existing_rows(exclude: set[str]) -> list[dict]:
    """Keep previously fetched rows for datasets this run does not re-fetch."""
    if not MANIFEST.is_file():
        return []
    rows = []
    for number, line in enumerate(MANIFEST.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = parse_json_line(line, f"{MANIFEST}:{number}")
        if row["dataset"] not in exclude:
            rows.append(row)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="fetch one dataset id")
    ap.add_argument("--skip-git", action="store_true")
    args = ap.parse_args()

    CORPUS.mkdir(parents=True, exist_ok=True)
    sources = [s for s in SOURCES if not args.only or s["dataset"] == args.only]
    covered = {source["dataset"] for source in sources}
    if not args.only and not args.skip_git:
        covered |= {repo["repo"] for repo in GIT_REPOS}
    rows = existing_rows(exclude=covered)
    for source in sources:
        if args.only and source["dataset"] != args.only:
            continue
        if source["files"] == "ALL":
            names = [f["path"] for f in list_files(source["dataset"], source["revision"])]
        else:
            names = source["files"]
        print(f"fetching {source['dataset']} ({len(names)} files)", flush=True)
        for name in names:
            row = fetch_file(source["dataset"], source["revision"], name)
            flags = ""
            if not row["oid_match"]:
                flags += "  <-- LFS oid mismatch"
            if row["lfs_pointer_bytes"] not in (None, row["bytes"]):
                flags += "  <-- LFS size mismatch"
            print(f"  {row['bytes']:>10} {name}{flags}", flush=True)
            rows.append(
                {
                    **row,
                    "modality": source["modality"],
                    "license": source["license"],
                    "snapshot_at": source["snapshot_at"],
                    "annotation_source": source["annotation_source"],
                }
            )
    if not args.only and not args.skip_git:
        for repo in GIT_REPOS:
            print(f"cloning {repo['repo']}", flush=True)
            rows.append(
                {
                    **fetch_git(repo),
                    "modality": repo["modality"],
                    "license": "see-repo",
                    "snapshot_at": None,
                    "annotation_source": repo["annotation_source"],
                }
            )

    rows.sort(key=lambda r: (r["dataset"], r["path"]))
    MANIFEST.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    print(f"manifest: {len(rows)} files, {sum(r['bytes'] for r in rows) / 1e9:.2f} GB -> {MANIFEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
