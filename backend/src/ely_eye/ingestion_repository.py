"""Repository context: file structure, call graph, git history, written out as atoms."""

from __future__ import annotations

import ast
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from .config import Settings
from .db import Database
from .ingestion_common import (
    REPOSITORY_COMMIT_LIMIT,
    REPOSITORY_INDEX_LIMIT,
    SUPPORTED_CODE_EXTENSIONS,
    IngestBatch,
    file_kind,
    relative_path,
)
from .schemas import (
    EvidenceAtom,
    Modality,
    SourceRecord,
    TrustScores,
)
from .storage import (
    ObjectStore,
    safe_source_id,
    sha256_bytes,
    token_equivalent,
)


class RepositoryIngest:
    settings: Settings
    db: Database
    objects: ObjectStore

    def _ingest_repository_context(self, root: Path, files: list[Path]) -> IngestBatch:
        code_files = [path for path in files if path.suffix.lower() in SUPPORTED_CODE_EXTENSIONS]
        git_root = find_git_root(root)
        if not code_files and git_root is None:
            return IngestBatch(sources=[], atoms=[])

        context = build_repository_context(root, files, code_files, git_root)
        payload = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest = sha256_bytes(payload)
        source = SourceRecord(
            source_id=safe_source_id(root, digest),
            path=str(root),
            kind="code_repository",
            mime="application/vnd.ely-eye.repository+json",
            sha256=digest,
            size_bytes=len(payload),
            metadata={
                "file_count": context["structure"]["file_count"],
                "indexed_file_count": context["structure"]["indexed_file_count"],
                "code_file_count": context["code"]["file_count"],
                "git_available": context["git"]["available"],
            },
        )
        atom = EvidenceAtom(
            atom_id=f"{source.source_id}:text",
            modality=Modality.code,
            source_id=source.source_id,
            source=str(root),
            text=json.dumps(context, ensure_ascii=False, indent=2),
            trust=TrustScores(parser=1.0, ocr=0.0, model=0.0),
            token_equivalent=token_equivalent(json.dumps(context, ensure_ascii=False)),
            metadata=context,
        )
        return IngestBatch(sources=[source], atoms=[atom])

def build_repository_context(
    root: Path,
    files: list[Path],
    code_files: list[Path],
    git_root: Path | None,
) -> dict[str, Any]:
    structure_entries = [file_structure_entry(root, path) for path in sorted(files)[:REPOSITORY_INDEX_LIMIT]]
    code_entries = [code_context_entry(root, path) for path in sorted(code_files)[:REPOSITORY_INDEX_LIMIT]]
    git_context = collect_git_context(git_root) if git_root is not None else {"available": False}
    return {
        "format": "ely-eye-repository-context-v1",
        "root": str(root),
        "structure": {
            "file_count": len(files),
            "indexed_file_count": len(structure_entries),
            "limit": REPOSITORY_INDEX_LIMIT,
            "files": structure_entries,
        },
        "code": {
            "file_count": len(code_files),
            "indexed_file_count": len(code_entries),
            "files": code_entries,
            "call_graph": repository_call_graph(code_entries),
        },
        "git": git_context,
        "issue_pr_history": extract_issue_pr_history(git_context),
    }


def file_structure_entry(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": relative_path(root, path),
        "suffix": path.suffix.lower(),
        "kind": file_kind(path),
        "size_bytes": path.stat().st_size,
    }


def code_context_entry(root: Path, path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    symbols = extract_symbols(path, text)
    return {
        "path": relative_path(root, path),
        "language": path.suffix.lower().lstrip("."),
        "line_count": text.count("\n") + 1,
        "symbols": symbols,
    }


def repository_call_graph(code_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for entry in code_entries:
        declared = entry.get("symbols")
        symbols = declared if isinstance(declared, dict) else {}
        for call in symbols.get("calls", []):
            if not isinstance(call, dict):
                continue
            caller = call.get("caller")
            callee = call.get("callee")
            if caller and callee:
                edges.append({"path": entry["path"], "caller": caller, "callee": callee})
    return edges


def collect_git_context(root: Path) -> dict[str, Any]:
    commits = [
        parse_git_log_line(line)
        for line in run_git(root, ["log", f"--max-count={REPOSITORY_COMMIT_LIMIT}", "--pretty=format:%H%x09%an%x09%aI%x09%s"]).splitlines()
        if line.strip()
    ]
    commits = [commit for commit in commits if commit]
    return {
        "available": True,
        "root": str(root),
        "head": run_git(root, ["rev-parse", "HEAD"]).strip() or None,
        "branch": run_git(root, ["branch", "--show-current"]).strip() or None,
        "remotes": parse_git_remotes(run_git(root, ["remote", "-v"])),
        "recent_commits": commits,
    }


def parse_git_log_line(line: str) -> dict[str, str] | None:
    parts = line.split("\t", 3)
    if len(parts) != 4:
        return None
    commit_hash, author, authored_at, subject = parts
    return {"hash": commit_hash, "author": author, "authored_at": authored_at, "subject": subject}


def parse_git_remotes(output: str) -> list[dict[str, str]]:
    remotes: list[dict[str, str]] = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            remotes.append({"name": parts[0], "url": parts[1], "kind": parts[2].strip("()")})
    return remotes


def extract_issue_pr_history(git_context: dict[str, Any]) -> dict[str, Any]:
    references: dict[str, set[int]] = {"issues": set(), "pull_requests": set()}
    for commit in git_context.get("recent_commits", []):
        if not isinstance(commit, dict):
            continue
        subject = str(commit.get("subject") or "")
        for number in re.findall(r"(?:fixes|closes|resolves)\s+#(\d+)", subject, flags=re.IGNORECASE):
            references["issues"].add(int(number))
        for number in re.findall(r"(?:pull request|pr)\s*#?(\d+)", subject, flags=re.IGNORECASE):
            references["pull_requests"].add(int(number))
        for number in re.findall(r"\(#(\d+)\)", subject):
            references["pull_requests"].add(int(number))
    return {
        "source": "local_git_commit_history",
        "issues": sorted(references["issues"]),
        "pull_requests": sorted(references["pull_requests"]),
    }


def run_git(root: Path, args: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout if completed.returncode == 0 else ""


def find_git_root(path: Path) -> Path | None:
    current = path if path.is_dir() else path.parent
    while True:
        if (current / ".git").exists():
            return current
        if current.parent == current:
            return None
        current = current.parent


def extract_symbols(path: Path, text: str) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".py":
        return extract_python_symbols(text)
    symbols = re.findall(
        r"\b(?:class|function|interface|type|enum|struct|fn|func)\s+([A-Za-z_][A-Za-z0-9_]*)",
        text,
    )
    constants = re.findall(r"\b(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=", text)
    calls = extract_generic_calls(text)
    return {"symbols": sorted(set(symbols)), "bindings": sorted(set(constants)), "calls": calls}


def extract_python_symbols(text: str) -> dict[str, Any]:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return {
            "classes": [],
            "functions": [],
            "imports": [],
            "calls": extract_generic_calls(text),
            "parse_error": f"{exc.msg} at line {exc.lineno}",
        }
    classes: list[str] = []
    functions: list[str] = []
    imports: list[str] = []
    calls: list[dict[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)
        elif isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    call_visitor = PythonCallGraphVisitor()
    call_visitor.visit(tree)
    calls.extend(call_visitor.calls)
    return {
        "classes": sorted(set(classes)),
        "functions": sorted(set(functions)),
        "imports": sorted(set(imports)),
        "calls": calls,
    }


class PythonCallGraphVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.current: str | None = None
        self.calls: list[dict[str, str]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        previous = self.current
        self.current = node.name
        self.generic_visit(node)
        self.current = previous

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        previous = self.current
        self.current = node.name
        self.generic_visit(node)
        self.current = previous

    def visit_Call(self, node: ast.Call) -> Any:
        if self.current:
            callee = python_call_name(node.func)
            if callee:
                self.calls.append({"caller": self.current, "callee": callee})
        self.generic_visit(node)


def python_call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = python_call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def extract_generic_calls(text: str) -> list[dict[str, str]]:
    calls: list[dict[str, str]] = []
    current = "<module>"
    function_pattern = re.compile(r"\b(?:function|fn|func)\s+([A-Za-z_][A-Za-z0-9_]*)|([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\([^)]*\)\s*=>")
    call_pattern = re.compile(r"\b([A-Za-z_][A-Za-z0-9_.]*)\s*\(")
    keywords = {"if", "for", "while", "switch", "catch", "return", "function"}
    for line in text.splitlines():
        function_match = function_pattern.search(line)
        if function_match:
            current = next(group for group in function_match.groups() if group)
        for callee in call_pattern.findall(line):
            root = callee.split(".", 1)[0]
            if root not in keywords and callee != current:
                calls.append({"caller": current, "callee": callee})
    return calls


