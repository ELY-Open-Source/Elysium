"""Subset the site's two open-licence serifs to the characters the site uses.

Usage: python3 scripts/subset_fonts.py <dir holding NotoSerifSC[wght].ttf and Newsreader[opsz,wght].ttf>

Sources: github.com/google/fonts ofl/notoserifsc and ofl/newsreader (SIL Open Font License 1.1).
Re-run after any copy change; the script fails if a used character is missing from a font.
"""

import sys
import unicodedata
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

SITE = Path(__file__).resolve().parent.parent
OUT = SITE / "public" / "fonts"


def used_text() -> str:
    files = [SITE / "index.html", *sorted((SITE / "src").rglob("*.ts"))]
    return "".join(f.read_text(encoding="utf-8") for f in files)


def is_cjk(ch: str) -> bool:
    name = unicodedata.name(ch, "")
    return name.startswith(("CJK", "FULLWIDTH", "IDEOGRAPHIC")) or "　" <= ch <= "〿"


def write(font: TTFont, chars: set[str], path: Path) -> None:
    cmap = font.getBestCmap()
    missing = sorted(ch for ch in chars if ord(ch) not in cmap and not ch.isspace())
    if missing:
        raise SystemExit(f"{path.name}: the font has no glyph for {''.join(missing)!r}")
    options = subset.Options()
    options.flavor = "woff2"
    options.layout_features = ["kern", "liga", "pnum", "tnum", "lnum", "onum"]
    options.name_IDs = ["*"]
    sub = subset.Subsetter(options)
    sub.populate(unicodes=[ord(ch) for ch in chars])
    sub.subset(font)
    font.flavor = "woff2"
    font.save(path)
    print(f"{path.name}: {len(chars)} characters, {path.stat().st_size:,} bytes")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    src = Path(sys.argv[1])
    text = used_text()
    ascii_printable = {chr(c) for c in range(0x20, 0x7F)}
    cjk = {ch for ch in text if is_cjk(ch)}
    latin = ascii_printable | {ch for ch in text if ord(ch) > 0x7E and not is_cjk(ch) and ch.isprintable()}
    OUT.mkdir(parents=True, exist_ok=True)
    for weight in (500, 700):
        font = instancer.instantiateVariableFont(TTFont(src / "NotoSerifSC[wght].ttf"), {"wght": weight})
        write(font, cjk | ascii_printable, OUT / f"NotoSerifSC-{weight}.woff2")
    news = instancer.instantiateVariableFont(TTFont(src / "Newsreader[opsz,wght].ttf"), {"opsz": 24, "wght": (400, 700)})
    write(news, latin, OUT / "Newsreader.woff2")


if __name__ == "__main__":
    main()
