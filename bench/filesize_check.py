"""Fail when a tracked source file outgrows the line budget the repo agreed to."""

import subprocess
from pathlib import Path

LINE_LIMIT = 500
CODE_SUFFIXES = (".py", ".go", ".ts", ".tsx", ".mjs", ".css", ".sh", ".ps1")


def tracked_files() -> list[Path]:
    """Every file git tracks under the repository root."""
    listing = subprocess.run(
        ["git", "ls-files"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    if listing.returncode != 0:
        raise SystemExit(f"git ls-files failed: {listing.stderr.strip()}")
    return [Path(name) for name in listing.stdout.split() if name.endswith(CODE_SUFFIXES)]


def line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8", errors="replace").splitlines())


def offenders(root: Path, files: list[Path] | None = None) -> list[tuple[int, str]]:
    """Files over the budget, biggest first."""
    rows: list[tuple[int, str]] = []
    for name in files if files is not None else tracked_files():
        path = root / name
        if not path.is_file():
            continue
        lines = line_count(path)
        if lines > LINE_LIMIT:
            rows.append((lines, str(name)))
    return sorted(rows, reverse=True)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    over = offenders(root)
    if not over:
        print(f"OK: no tracked source file exceeds {LINE_LIMIT} lines")
        return
    for lines, name in over:
        print(f"{lines:5d}  {name}")
    raise SystemExit(f"{len(over)} files exceed the {LINE_LIMIT}-line budget")


if __name__ == "__main__":
    main()
