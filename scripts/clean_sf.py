"""Turn one Software Foundations volume's coqdoc HTML into e-reader-friendly chapter files.

Usage: calibre-debug scripts/clean_sf.py -- <volume-dir> <out-dir>
(runs under Calibre's bundled Python for its HTML5 parser and lxml)

Reads <volume-dir>/toc.html for chapter order, writes <out-dir>/<Chapter>.html for each
chapter, <out-dir>/_about.html (this edition, and the book's licence notice, which the
licence requires in every copy), <out-dir>/sf-epub.css and <out-dir>/_order.html (the entry
file for Calibre).
Regular expressions do the coqdoc-specific rewrites; html5_parser then repairs the
loose HTML (and coqdoc's own markup bugs) the way a browser would, and lxml writes XHTML.
"""
import html
import re
import sys
from pathlib import Path
from xml.dom import minidom

from html5_parser import parse as html5_parse
from lxml import etree

SKIP = {"toc.html", "index.html", "coqindex.html", "deps.html"}
SITE = "https://softwarefoundations.cis.upenn.edu"
REPO = "https://github.com/SaltedTan/sf-epub"

CSS = r"""
body { margin: 0; padding: 0; }
h1.libtitle { font-size: 1.6em; margin: 0 0 1em 0; line-height: 1.2; }
h1.libtitle .subtitle { display: block; font-size: 0.6em; font-weight: normal; margin-top: 0.3em; }
h1.section { font-size: 1.35em; margin-top: 1.4em; }
h2.section { font-size: 1.2em; margin-top: 1.2em; }
h3.section { font-size: 1.05em; margin-top: 1em; }
h4.section { font-size: 0.95em; margin: 1.2em 0 0.3em 0; padding: 0.2em 0.5em;
             border-left: 0.25em solid #8a9cc9; background-color: rgba(138,156,201,0.15); }
.paragraph { height: 0.5em; }
ul.doclist { margin-top: 0; margin-bottom: 0; }

/* Displayed Rocq code: one block per line, wrapped lines indented under their start. */
div.code { font-family: Menlo, "DejaVu Sans Mono", monospace; font-size: 0.82em;
           line-height: 1.35; margin: 0.5em 0 0.7em 0; }
div.code .ln { padding-left: 1.5em; text-indent: -1.5em; overflow-wrap: anywhere; }
div.code .blank { height: 0.6em; }
div.proofscript { margin: 0; padding-left: 0.6em; border-left: 0.15em solid rgba(128,128,128,0.35); }

.inlinecode { font-family: Menlo, "DejaVu Sans Mono", monospace; font-size: 0.9em;
              white-space: pre-wrap; }
.inlinecode br { display: none; }
.inlinecode.inlineblock { font-size: 0.72em; line-height: 1.3; }
.nowrap { white-space: nowrap; }
pre { font-family: Menlo, "DejaVu Sans Mono", monospace; font-size: 0.7em; line-height: 1.3; white-space: pre-wrap; overflow-wrap: anywhere; }

/* Inference rules. */
table.infrule { border: 0; margin: 0.5em auto 1em auto; }
td.infrule { font-family: Menlo, "DejaVu Sans Mono", monospace; font-size: 0.85em;
             text-align: center; padding: 0; line-height: 1.2; }
tr.infrulemiddle hr { margin: 1px 0; }
td.infrulenamecol { font-size: 0.75em; padding-left: 0.8em; opacity: 0.7; }

/* Syntax colours: each about 4-5:1 against white and against black, so they stay readable
   in Books' white, sepia and night themes. No prefers-color-scheme block: on iPad that follows
   the system setting, not the Books theme. Plain identifiers keep the theme's text colour. */
.id-keyword, .id-constructor { color: #5b8a1e; }
.id-tactic { color: #c0661a; }
.id-var, .id-variable, .id-binder { color: #a64ca6; }
.id-definition, .id-abbreviation, .id-lemma, .id-instance, .id-projection,
.id-method, .id-axiom { color: #2e8b47; }
.id-inductive, .id-record, .id-class { color: #2f7fbf; }
.id-notation { color: #808080; }
.comment { color: #808080; font-style: italic; }
.inlinecode [class^="id-"] { color: inherit; }
"""

TOKEN = re.compile(r"(<div\b[^>]*>|</div>|<br\s*/>|<hr class='doublespaceincode'\s*/>|<span\b[^>]*>|</span>)")


def split_code_lines(inner: str) -> str:
    """Rewrite the inside of a div.code: each <br/>-terminated line becomes <div class="ln">.

    Divs (proof scripts) pass through as structure; spans left open at a line break are
    closed and reopened on the next line so every line is well nested.
    """
    out, line, open_spans = [], [], []

    def flush(force_blank=False):
        text = "".join(line)
        if text.strip() or force_blank:
            if text.strip():
                out.append('<div class="ln">' + "".join(open_spans_at_start) + text
                           + "</span>" * len(open_spans) + "</div>")
            else:
                out.append('<div class="blank"></div>')
        line.clear()

    open_spans_at_start = []
    for tok in TOKEN.split(inner):
        if not tok:
            continue
        if tok.startswith("<div"):
            flush()
            out.append(tok)
            open_spans_at_start = list(open_spans)
        elif tok == "</div>":
            flush()
            out.append(tok)
            open_spans_at_start = list(open_spans)
        elif tok.startswith("<br"):
            flush()
            open_spans_at_start = list(open_spans)
        elif tok.startswith("<hr"):
            flush()
            out.append('<div class="blank"></div>')
            open_spans_at_start = list(open_spans)
        elif tok.startswith("<span"):
            open_spans.append(tok)
            line.append(tok)
        elif tok == "</span>":
            if open_spans:
                open_spans.pop()
            line.append(tok)
        else:
            line.append(tok)
    flush()
    return "\n".join(out)


def clean_chapter(src: str) -> tuple[str, str]:
    title = html.unescape(re.search(r"<title>(.*?)</title>", src, re.S).group(1)).strip()
    m = re.search(r'<div id="main">(.*?)<div id="footer">', src, re.S)
    body = m.group(1)
    body = re.sub(r"</div>\s*$", "", body.rstrip())  # the closing tag of #main

    # Proof toggles: drop the "+" buttons, keep every proof visible.
    body = re.sub(r'<div class="togglescript"[^>]*><span class="show"></span></div>\s*', "", body)
    body = re.sub(r'(<div class="proofscript") id="[^"]*" onclick="[^"]*"', r"\1", body)

    # Identifier links: unwrap. On a small touch screen they are accidental taps, and many
    # of coqdoc's targets are invalid (markup inside href, ':' in ids, links off-book).
    body = re.sub(r'<a (?:id="[^"]*" )?class="idref" href="[^"]*">', "", body)
    body = re.sub(r"(<span class=\"id\" title=\"[^\"]*\">[^<]*</span>)</a>", r"\1", body)
    # The </a> tags left behind are removed by fix_unbalanced_anchors().

    # coqdoc's title-based colouring -> classes, no hover tooltips.
    body = re.sub(r'<span class="id" title="([a-z]+)">', r'<span class="id-\1">', body)

    # Code blocks: one div per line.
    body = rewrite_code_divs(body, lambda inner: '<div class="code">' + split_code_lines(inner) + "</div>")

    # coqdoc writes some external links as broken markup: keep the URL and its text.
    body = re.sub(r'<a href="([^"]*)"><span class="inlineref" <a href=\'[^\']*\'>(.*?)</span></a>([^<]*)</a>',
                  r'<a href="\1">\2</a>\3', body)
    body = re.sub(r'<a href="([^"]*)" <a href=\'[^\']*\'>(.*?)</a>([^<]*)</a>', r'<a href="\1">\2</a>\3', body)
    # coqdoc subscripts digits even inside URLs (ws11 -> ws<sub>11</sub>); undo that in hrefs.
    body = re.sub(r'href="[^"]*"', lambda m: re.sub(r"</?sub>", "", m.group(0)), body)
    # Bibliography entries are written as <a target="Key">; make them anchors.
    body = re.sub(r'<a target="([^"]*)">', lambda m: '<a id="' + m.group(1).replace(" ", "_") + '">', body)
    body = re.sub(r'href="Bib\.html#([^"]*)"', lambda m: 'href="Bib.html#' + m.group(1).replace(" ", "_") + '"', body)
    body = close_runaway_inline(body)
    # The exercise checkbox: <font size=-2>&#9744;</font>
    body = re.sub(r"<font size=-2>(.*?)</font>", r'<span class="box">\1</span>', body)
    body = body.replace("<center>", '<div style="text-align:center">').replace("</center>", "</div>")
    return title, body


def to_xhtml(body: str) -> str:
    """Parse as HTML5 (repairing what browsers repair) and serialise the body as XML."""
    root = html5_parse("<!DOCTYPE html><html><head></head><body>" + body + "</body></html>",
                       treebuilder="lxml", sanitize_names=True)
    b = root.find("body")
    for el in b.iter():
        for a in list(el.attrib):
            if a in ("onclick", "title") or a.startswith("on"):
                del el.attrib[a]
    # A multi-line inline-code span is a displayed, column-aligned block (grammars in PLF):
    # set it smaller, as the site's <pre> blocks are, so its columns survive a narrow screen.
    for el in b.iter("span"):
        if "inlinecode" in el.get("class", "").split() and "\n" in "".join(el.itertext()).strip():
            el.set("class", el.get("class") + " inlineblock")
    xml = etree.tostring(b, encoding="unicode", method="xml")
    return re.sub(r"^<body[^>]*>|</body>$", "", xml.strip())


RUNAWAY_FIXES = []


def close_runaway_inline(body: str) -> str:
    """Close an <i> or <b> still open when a block (<div>) starts: a missing '_' in the .v source."""
    out, open_tags = [], []
    for tok in re.split(r"(<i>|</i>|<b>|</b>|<div\b[^>]*>)", body):
        if tok in ("<i>", "<b>"):
            open_tags.append(tok[1])
        elif tok in ("</i>", "</b>"):
            if open_tags and open_tags[-1] == tok[2]:
                open_tags.pop()
        elif tok.startswith("<div"):
            while open_tags:
                t = open_tags.pop()
                out.append(f"</{t}>")
                RUNAWAY_FIXES.append(t)
        out.append(tok)
    return "".join(out)


def rewrite_code_divs(body: str, fn) -> str:
    """Find each <div class="code"> ... matching </div> (nested divs allowed) and rewrite it."""
    out, i = [], 0
    opener = '<div class="code">'
    while True:
        j = body.find(opener, i)
        if j < 0:
            out.append(body[i:])
            break
        out.append(body[i:j])
        depth, k = 0, j
        for t in re.finditer(r"<div\b[^>]*>|</div>", body[j:]):
            depth += 1 if t.group(0).startswith("<div") else -1
            if depth == 0:
                k = j + t.end()
                break
        inner = body[j + len(opener): k - len("</div>")]
        out.append(fn(inner))
        i = k
    return "".join(out)


def fix_unbalanced_anchors(body: str) -> str:
    """Remove </a> tags that no longer have an opening <a>."""
    out, depth = [], 0
    for tok in re.split(r"(<a\b[^>]*>|</a>)", body):
        if tok.startswith("<a ") or tok == "<a>":
            depth += 1
            out.append(tok)
        elif tok == "</a>":
            if depth > 0:
                depth -= 1
                out.append(tok)
        else:
            out.append(tok)
    return "".join(out)


def about_page(vol: Path, book_title: str) -> tuple[str, list[str], str]:
    """The last page: what this edition is, what was changed, and the book's licence verbatim."""
    index = (vol / "index.html").read_text(encoding="utf-8")
    version = re.search(r"Version [^<]*", index)
    version = version.group(0).strip() if version else "unknown version"
    authors = re.search(r'<div class="mediumauthors">(.*?)</div>', index, re.S)
    authors = [a.strip() for a in re.split(r"<br\s*/?>", authors.group(1)) if a.strip()] if authors else []
    licence = (vol / "LICENSE").read_text(encoding="utf-8").strip()
    source = f"{SITE}/{vol.name}-current/"
    e = html.escape
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><meta charset="utf-8"/><title>About this edition</title>
<link href="sf-epub.css" rel="stylesheet" type="text/css"/></head>
<body>
<h1 class="libtitle">About this edition</h1>
<p><i>{e(book_title)}</i>, by {e(", ".join(authors))}. {e(version)}.</p>
<p>This is an <b>unofficial</b> EPUB conversion of the book's HTML edition, made for reading on
e-readers. It is not affiliated with or endorsed by the authors. The official edition, and the
Rocq sources you need to do the exercises, are at <a href="{source}">{e(source)}</a>.</p>
<p>The book's text is unchanged. Proofs that the website folds away are shown in full; the "+" buttons that unfold them, the site's navigation
and its background image are removed (the cover is the book's own, from its home page); identifier links inside code are kept as coloured text,
not links; and one unclosed italic in the source is closed at the end of its paragraph. It was
made with the scripts at <a href="{REPO}">{e(REPO)}</a>.</p>
<p>The book asks readers not to post solutions to its exercises in public places.</p>
<h2 class="section">Licence</h2>
<p>Software Foundations is distributed under the following licence, reproduced as it appears in
the book's source distribution:</p>
<pre>{e(licence)}</pre>
</body>
</html>
""", authors, version


def main():
    vol, outdir = Path(sys.argv[1]), Path(sys.argv[2])
    outdir.mkdir(parents=True, exist_ok=True)
    toc = (vol / "toc.html").read_text(encoding="utf-8")
    chapters = []
    for name in re.findall(r'href="([A-Za-z0-9]+\.html)', toc):
        if name not in SKIP and name not in chapters:
            chapters.append(name)
    book_title = html.unescape(re.search(r"<title>(.*?)</title>",
                                         (vol / "index.html").read_text(encoding="utf-8")).group(1))
    (outdir / "sf-epub.css").write_text(CSS, encoding="utf-8")
    bad = 0
    for name in chapters:
        title, body = clean_chapter((vol / name).read_text(encoding="utf-8"))
        body = to_xhtml(fix_unbalanced_anchors(body))
        # Links to pages that are not chapters of this volume become plain text.
        def link(mm):
            href = mm.group(1)
            target = href.split("#")[0]
            if href.startswith(("http://", "https://", "mailto:")) or href.startswith("#") \
                    or target in chapters:
                return mm.group(0)
            return '<a class="deadlink">'
        body = re.sub(r'<a href="([^"]*)">', link, body)
        doc = ('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
               '<html xmlns="http://www.w3.org/1999/xhtml">\n<head>\n<meta charset="utf-8"/>\n'
               f"<title>{html.escape(title)}</title>\n"
               '<link href="sf-epub.css" rel="stylesheet" type="text/css"/>\n</head>\n<body>\n'
               + body + "\n</body>\n</html>\n")
        try:
            minidom.parseString(doc.encode("utf-8"))
        except Exception as e:  # report, still write, so it can be inspected
            bad += 1
            print(f"NOT WELL-FORMED: {name}: {e}", file=sys.stderr)
        (outdir / name).write_text(doc, encoding="utf-8")
    about, authors, version = about_page(vol, book_title)
    (outdir / "_about.html").write_text(about, encoding="utf-8")
    # Read by build.sh for the EPUB's metadata: title, authors and their sort keys (Calibre's
    # " & " lists; "Last, First", as Calibre's own default makes them), version.
    sort_keys = [a.rsplit(" ", 1)[1] + ", " + a.rsplit(" ", 1)[0] if " " in a else a for a in authors]
    (outdir / "_meta.txt").write_text(
        f"{book_title}\n{' & '.join(authors)}\n{' & '.join(sort_keys)}\n{version}\n", encoding="utf-8")
    entries = "\n".join(f'<li><a href="{c}">{c[:-5]}</a></li>' for c in chapters + ["_about.html"])
    (outdir / "_order.html").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"><head><meta charset="utf-8"/>'
        f"<title>{html.escape(book_title)}</title></head><body><ul>{entries}</ul></body></html>\n",
        encoding="utf-8")
    print(f"{book_title}: {len(chapters)} chapters, {bad} not well-formed, "
          f"{len(RUNAWAY_FIXES)} unclosed <i>/<b> closed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
