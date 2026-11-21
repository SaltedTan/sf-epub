#!/usr/bin/env bash
# Screenshot a page of a built EPUB at an iPad mini's portrait width, to check layout.
#
#   scripts/shot.sh <book.epub> <Chapter> <text> <out.png> [width]
#
# Opens the chapter's file (Calibre may split a chapter: <Chapter>_split_NNN.html; the first
# file containing <text> is used), starting at the block that holds <text>, in headless Chrome.
# Width is in CSS pixels (default 744, iPad mini 6th gen portrait; try 430 for a large font).
# Needs google-chrome. Chrome only approximates Apple Books: fonts and margins differ.
set -euo pipefail
epub=$1 chapter=$2 needle=$3 out=$4 width=${5:-744}
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
python3 -m zipfile -e "$epub" "$tmp"
file=$(grep -l -F -- "$needle" "$tmp/$chapter".html "$tmp/$chapter"_split_*.html 2>/dev/null | head -1 || true)
[[ -n $file ]] || { echo "'$needle' not found in $chapter" >&2; exit 1; }
# Start the page at the block holding the text, rather than scrolling to it: headless Chrome
# sometimes captures a blank frame after a long scroll.
python3 -I - "$file" "$needle" "$tmp/_shot.html" <<'EOF'
import sys
s = open(sys.argv[1], encoding="utf-8").read()
i = s.find(sys.argv[2])
j = max(s.rfind(t, 0, i) for t in ('<div class="code', '<div class="doc', "<h1", "<h2"))
body = s.find(">", s.find("<body")) + 1
open(sys.argv[3], "w", encoding="utf-8").write(s[:body] + s[j:])
EOF
google-chrome --headless=new --disable-gpu --hide-scrollbars --window-size="$width",1133 \
	--force-device-scale-factor=1.5 --blink-settings=preferredColorScheme=1 \
	--virtual-time-budget=4000 --screenshot="$(realpath "$out")" "file://$tmp/_shot.html" >/dev/null 2>&1
echo "$out"
