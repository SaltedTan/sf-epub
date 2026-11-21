#!/usr/bin/env bash
# Build EPUBs of Software Foundations Volume 1 (lf) and Volume 2 (plf).
#
#   ./build.sh              both volumes
#   ./build.sh lf           one volume
#   REFRESH=1 ./build.sh    download the book again (to pick up a new release)
#
# Downloads the current release of each volume from the official site, cleans its HTML
# (scripts/clean_sf.py), checks that no chapter lost or gained a word (scripts/compare_text.py)
# and converts it with Calibre. Writes out/SF<n>-<Title-With-Hyphens>.epub.
#
# Uses Calibre's ebook-convert and calibre-debug from PATH if present; otherwise, on x86-64
# Linux, downloads a pinned portable Calibre into .cache/. If Java is installed, validates the
# result with a pinned epubcheck (reported, not fatal).
set -euo pipefail
cd "$(dirname "$0")"

SITE=https://softwarefoundations.cis.upenn.edu
CALIBRE_VERSION=9.18.0
CALIBRE_SHA256=da638166fb3dd204be77cf0f871a40d803536b3e5948969c5233b8e4f1e1dbe6
EPUBCHECK_VERSION=5.4.0
EPUBCHECK_SHA256=33350c61038e71dfb3d45a76aed04bf5481e6d5500cb780f6e98db8bbd15a28c
CACHE=.cache
mkdir -p "$CACHE" out

sha256() { if command -v sha256sum >/dev/null; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -d' ' -f1; }

fetch() { # fetch <url> <file> [sha256]
	if [[ ! -f $2 ]]; then
		echo "downloading $1"
		curl -fsSL -o "$2.part" "$1" && mv "$2.part" "$2"
	fi
	if [[ -n ${3:-} && $(sha256 "$2") != "$3" ]]; then
		echo "checksum mismatch for $2; delete it and retry" >&2
		exit 1
	fi
}

# --- Calibre ---------------------------------------------------------------------------
if command -v ebook-convert >/dev/null && command -v calibre-debug >/dev/null; then
	CONVERT=ebook-convert DEBUG=calibre-debug
elif [[ $(uname -s) == Linux && $(uname -m) == x86_64 ]]; then
	dir=$CACHE/calibre-$CALIBRE_VERSION
	if [[ ! -x $dir/ebook-convert ]]; then
		fetch "https://github.com/kovidgoyal/calibre/releases/download/v$CALIBRE_VERSION/calibre-$CALIBRE_VERSION-x86_64.txz" \
			"$CACHE/calibre-$CALIBRE_VERSION-x86_64.txz" "$CALIBRE_SHA256"
		mkdir -p "$dir" && tar xJf "$CACHE/calibre-$CALIBRE_VERSION-x86_64.txz" -C "$dir"
	fi
	CONVERT=$dir/ebook-convert DEBUG=$dir/calibre-debug
	export QT_QPA_PLATFORM=offscreen # no display needed
else
	echo "Install Calibre and put ebook-convert and calibre-debug on PATH" >&2
	echo "(on macOS: /Applications/calibre.app/Contents/MacOS)." >&2
	exit 1
fi

# --- One volume ------------------------------------------------------------------------
build() { # build <lf|plf>
	local v=$1 num
	case $v in lf) num=1 ;; plf) num=2 ;; *) echo "unknown volume '$v' (lf or plf)" >&2; exit 1 ;; esac
	local tgz=$CACHE/$v.tgz src=$CACHE/src-$v work=$CACHE/clean-$v
	[[ -n ${REFRESH:-} ]] && rm -f "$tgz"
	fetch "$SITE/$v-current/$v.tgz" "$tgz"
	rm -rf "$src" "$work" && mkdir -p "$src"
	# The tarballs carry macOS metadata (._* files, xattr headers); skip it quietly.
	tar xzf "$tgz" -C "$src" --exclude='._*' 2>/dev/null
	"$DEBUG" scripts/clean_sf.py -- "$src/$v" "$work"
	"$DEBUG" scripts/compare_text.py -- "$src/$v" "$work" | tail -1

	local title authors author_sort version
	{ read -r title; read -r authors; read -r author_sort; read -r version; } < "$work/_meta.txt"
	# The cover: the volume's own cover image, as shown on the book's home page.
	local cover=$src/$v/common/media/image/${v}_icon.jpg
	[[ -f $cover ]] || { echo "cover image $cover not found" >&2; exit 1; }
	local epub="out/SF$num-${title// /-}.epub"  # no spaces: GitHub renames release assets that have them
	"$CONVERT" "$work/_order.html" "$epub" \
		--max-levels=1 --title "$title" --authors "$authors" \
		--series "Software Foundations" --series-index "$num" \
		--cover "$cover" --preserve-cover-aspect-ratio \
		--publisher "University of Pennsylvania" --language en \
		--comments "$version. Unofficial EPUB conversion of $SITE/$v-current/ (see the last page)." \
		--level1-toc '//h:h1[contains(@class,"libtitle")]' \
		--level2-toc '//h:h1[contains(@class,"section")]' \
		--level3-toc '//h:h2[contains(@class,"section")]' \
		--chapter-mark none --page-breaks-before '//h:h1[contains(@class,"libtitle")]' \
		--disable-font-rescaling --epub-version 3 > "$CACHE/convert-$v.log" 2>&1 \
		|| { echo "ebook-convert failed; see $CACHE/convert-$v.log" >&2; exit 1; }
	python3 -I scripts/fix_author_sort.py "$epub" "$author_sort"
	echo "built $epub ($version)"
}

volumes=("$@")
[[ ${#volumes[@]} -eq 0 ]] && volumes=(lf plf)
for v in "${volumes[@]}"; do build "$v"; done

# --- Validation (optional) -------------------------------------------------------------
if command -v java >/dev/null; then
	jar=$CACHE/epubcheck-$EPUBCHECK_VERSION/epubcheck.jar
	if [[ ! -f $jar ]]; then
		fetch "https://github.com/w3c/epubcheck/releases/download/v$EPUBCHECK_VERSION/epubcheck-$EPUBCHECK_VERSION.zip" \
			"$CACHE/epubcheck-$EPUBCHECK_VERSION.zip" "$EPUBCHECK_SHA256"
		(cd "$CACHE" && python3 -m zipfile -e "epubcheck-$EPUBCHECK_VERSION.zip" .)
	fi
	for f in out/*.epub; do
		r=$(java -jar "$jar" "$f" 2>&1 || true)
		echo "epubcheck $f: $(grep -c '^ERROR' <<<"$r" || true) errors, $(grep -c '^FATAL' <<<"$r" || true) fatal"
	done
else
	echo "(java not found: skipped epubcheck)"
fi
