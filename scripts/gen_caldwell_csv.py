#!/usr/bin/env python3
import re
import sys
from pathlib import Path
from urllib.request import Request, urlopen

DEFAULT_SOURCE = "https://www.astropixels.com/caldwell/caldwellcat.html"


def main() -> int:
    out_path = Path("data/caldwell.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    source = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SOURCE
    raw = _read_source(source)
    rows = _parse_astropixels(raw)
    if not rows:
        print("No Caldwell rows parsed.", file=sys.stderr)
        return 1
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("caldwell_id,object_id\n")
        for caldwell_id, object_id in rows:
            f.write(f"{caldwell_id},{object_id}\n")
    print(f"Wrote {len(rows)} rows to {out_path}")
    return 0


def _read_source(source: str) -> str:
    if source.startswith("http://") or source.startswith("https://"):
        req = Request(source, headers={"User-Agent": "astrolabe/0.1"})
        return urlopen(req).read().decode("utf-8")
    path = Path(source)
    return path.read_text(encoding="utf-8")


def _parse_astropixels(html: str) -> list[tuple[str, str]]:
    rows = []
    for row in re.split(r"(?i)</tr>", html):
        m = re.search(r"\\bC\\s*(\\d{1,3})\\b", row)
        if not m:
            continue
        cal_num = int(m.group(1))
        obj = _extract_object_id(row)
        if not obj:
            continue
        rows.append((f"C{cal_num}", obj))
    if rows:
        return rows
    # fallback to text parsing
    text = _html_to_text(html)
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.search(r"\\bC\\s*(\\d{1,3})\\b", line)
        if not m:
            continue
        cal_num = int(m.group(1))
        obj = _extract_object_id(line)
        if not obj:
            continue
        rows.append((f"C{cal_num}", obj))
    return rows


def _extract_object_id(text: str) -> str | None:
    for pattern in (r"NGC\\s*\\d+", r"IC\\s*\\d+", r"Sh2-\\s*\\d+", r"Hyades"):
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            return m.group(0).replace(" ", "").upper()
    return None


def _html_to_text(html: str) -> str:
    # Preserve row boundaries for simple parsing.
    html = re.sub(r"(?i)</tr>", "\n", html)
    html = re.sub(r"(?i)<br\\s*/?>", "\n", html)
    html = re.sub(r"(?i)<td[^>]*>", " ", html)
    html = re.sub(r"(?i)</td>", " ", html)
    html = re.sub(r"(?i)<th[^>]*>", " ", html)
    html = re.sub(r"(?i)</th>", " ", html)
    html = re.sub(r"<[^>]+>", " ", html)
    html = html.replace("&nbsp;", " ")
    html = re.sub(r"[ \\t]+", " ", html)
    return html


if __name__ == "__main__":
    raise SystemExit(main())
