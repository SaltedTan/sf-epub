"""Compare the visible words of each original chapter (#main) with its cleaned version.

Usage: calibre-debug scripts/compare_text.py -- <volume-dir> <cleaned-dir>
Exits 1 if any chapter differs.
"""
import difflib
import re
import sys
from pathlib import Path

from html5_parser import parse


def words(path: Path, main_only: bool) -> list[str]:
    root = parse(path.read_text(encoding="utf-8"), treebuilder="lxml", sanitize_names=True)
    node = root
    if main_only:
        node = root.xpath('//*[@id="main"]')[0]
    for el in node.xpath('.//*[@class="togglescript"]|.//head|.//script|.//style'):
        el.getparent().remove(el)
    text = " ".join(node.itertext()).replace("\xa0", " ")
    return re.findall(r"\S+", text)


vol, cleaned = Path(sys.argv[1]), Path(sys.argv[2])
total_bad = 0
for f in sorted(cleaned.glob("*.html")):
    if f.name.startswith("_"):  # _order.html, _about.html: written by the cleaner, not chapters
        continue
    a, b = words(vol / f.name, True), words(f, False)
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    diffs = [op for op in sm.get_opcodes() if op[0] != "equal"]
    lost = sum(i2 - i1 for t, i1, i2, j1, j2 in diffs if t in ("delete", "replace"))
    added = sum(j2 - j1 for t, i1, i2, j1, j2 in diffs if t in ("insert", "replace"))
    flag = "" if not diffs else "  <-- differs"
    print(f"{f.name:22} {len(a):7} words -> {len(b):7}  lost {lost:4} added {added:4}{flag}")
    for t, i1, i2, j1, j2 in diffs[:3]:
        print(f"      {t}: {' '.join(a[i1:i2])[:100]!r} -> {' '.join(b[j1:j2])[:100]!r}")
    total_bad += bool(diffs)
print(f"{total_bad} chapters differ")
sys.exit(1 if total_bad else 0)
