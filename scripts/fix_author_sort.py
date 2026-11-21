"""Give each author in an EPUB its own sort key ("file-as").

Usage: python3 scripts/fix_author_sort.py <book.epub> "<Last, First> & <Last, First> & ..."

Calibre keeps one author-sort string per book and writes that whole string onto every
<dc:creator> of an EPUB 3. This rewrites the i-th author's file-as to the i-th key.
Standard library only; the mimetype entry stays first and uncompressed, as EPUB requires.
"""
import html
import re
import sys
import zipfile
from pathlib import Path

epub, keys = Path(sys.argv[1]), sys.argv[2].split(" & ")

with zipfile.ZipFile(epub) as z:
    entries = [(info, z.read(info.filename)) for info in z.infolist()]

opf_name = next(i.filename for i, _ in entries if i.filename.endswith(".opf"))
for n, (info, data) in enumerate(entries):
    if info.filename != opf_name:
        continue
    opf = data.decode("utf-8")
    ids = re.findall(r'<dc:creator id="([^"]+)"', opf)
    if len(ids) != len(keys):
        sys.exit(f"{epub}: {len(ids)} creators but {len(keys)} sort keys")
    for creator_id, key in zip(ids, keys):
        opf, count = re.subn(rf'(<meta refines="#{re.escape(creator_id)}" property="file-as">)[^<]*(</meta>)',
                             lambda m: m.group(1) + html.escape(key, quote=False) + m.group(2), opf)
        if count != 1:
            sys.exit(f"{epub}: expected one file-as for {creator_id}, found {count}")
    entries[n] = (info, opf.encode("utf-8"))

tmp = epub.with_suffix(".tmp")
with zipfile.ZipFile(tmp, "w") as out:
    for info, data in entries:
        compress = zipfile.ZIP_STORED if info.filename == "mimetype" else zipfile.ZIP_DEFLATED
        out.writestr(info, data, compress_type=compress)
tmp.replace(epub)
