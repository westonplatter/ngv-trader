#!/usr/bin/env python3
"""Generate docs/core/index.html — a table of core docs and their front matter.

Reads every .md file in docs/core/, parses YAML front matter, and writes a
standalone HTML file with a sortable table: file, topics, code_dirs_or_files,
description.

Usage:
    uv run python scripts/gen_core_index_html.py
"""

import re
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE_DIR = ROOT / "docs" / "core"
OUTPUT = CORE_DIR / "index.html"

FRONT_MATTER_RE = re.compile(r"^---\n(.*?)^---", re.DOTALL | re.MULTILINE)


def parse_front_matter(path: Path) -> dict[str, str] | None:
    """Extract front matter as a dict, or None if absent."""
    text = path.read_text()
    m = FRONT_MATTER_RE.match(text)
    if not m:
        return None
    raw = m.group(1)
    result: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        # Strip YAML list brackets and quotes: ["a", "b"] -> a, b
        if value.startswith("[") and value.endswith("]"):
            value = value[1:-1]
            value = re.sub(r'["\s]', "", value)
            value = value.replace(",", ", ")
        elif value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        result[key] = value
    return result


def render_html(rows: list[tuple[str, dict[str, str]]]) -> str:
    """Render the index HTML table."""
    rows_html = []
    for file_rel, fm in rows:
        topics = fm.get("topics", "—")
        code_dirs = fm.get("code_dirs_or_files", "—")
        desc = fm.get("description", "—")

        rows_html.append(f"""<tr>
      <td><code>{escape(file_rel)}</code></td>
      <td>{escape(topics)}</td>
      <td>{escape(code_dirs)}</td>
      <td>{escape(desc)}</td>
    </tr>""")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ngv-trader — Core Docs</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: #f8f9fa;
      color: #1f2937;
      padding: 2rem;
    }}
    h1 {{ font-size: 1.5rem; margin-bottom: 0.5rem; }}
    p.subtitle {{ color: #6b7280; margin-bottom: 1.5rem; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: #fff;
      border: 1px solid #e5e7eb;
      border-radius: 6px;
      overflow: hidden;
    }}
    th {{
      text-align: left;
      padding: 0.75rem 1rem;
      background: #f3f4f6;
      border-bottom: 2px solid #e5e7eb;
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: #374151;
      cursor: pointer;
      user-select: none;
    }}
    th:hover {{ background: #e5e7eb; }}
    td {{
      padding: 0.6rem 1rem;
      border-bottom: 1px solid #f3f4f6;
      font-size: 0.9rem;
      vertical-align: top;
    }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover {{ background: #f9fafb; }}
    code {{
      background: #f3f4f6;
      padding: 0.15rem 0.4rem;
      border-radius: 3px;
      font-size: 0.85rem;
    }}
    td:nth-child(4) {{ max-width: 400px; }}
    .sort-asc::after {{ content: " ▲"; font-size: 0.7rem; }}
    .sort-desc::after {{ content: " ▼"; font-size: 0.7rem; }}
  </style>
</head>
<body>
  <h1>Core Docs</h1>
  <p class="subtitle">{len(rows)} file(s) — click column headers to sort</p>
  <table id="docs-table">
    <thead>
      <tr>
        <th data-col="0">File</th>
        <th data-col="1">Topics</th>
        <th data-col="2">Code dirs / files</th>
        <th data-col="3">Description</th>
      </tr>
    </thead>
    <tbody>
      {"".join(rows_html)}
    </tbody>
  </table>
  <script>
    (function() {{
      const table = document.getElementById("docs-table");
      const thead = table.querySelector("thead");
      const tbody = table.querySelector("tbody");
      let currentCol = -1;
      let ascending = true;

      thead.addEventListener("click", function(e) {{
        const th = e.target.closest("th");
        if (!th) return;
        const col = parseInt(th.dataset.col, 10);
        if (col === currentCol) {{
          ascending = !ascending;
        }} else {{
          currentCol = col;
          ascending = true;
        }}
        // Update sort indicators
        thead.querySelectorAll("th").forEach(function(h) {{ h.classList.remove("sort-asc", "sort-desc"); }});
        th.classList.add(ascending ? "sort-asc" : "sort-desc");

        // Sort rows
        const rows = Array.from(tbody.querySelectorAll("tr"));
        rows.sort(function(a, b) {{
          const aText = a.cells[col].textContent.trim();
          const bText = b.cells[col].textContent.trim();
          const cmp = aText.localeCompare(bText);
          return ascending ? cmp : -cmp;
        }});
        rows.forEach(function(row) {{ tbody.appendChild(row); }});
      }});
    }})();
  </script>
</body>
</html>
"""


def main() -> None:
    if not CORE_DIR.is_dir():
        print(f"Error: {CORE_DIR} is not a directory", file=sys.stderr)
        sys.exit(1)

    md_files = sorted(CORE_DIR.glob("*.md"))
    if not md_files:
        print("No .md files found in docs/core/", file=sys.stderr)
        sys.exit(1)

    rows: list[tuple[str, dict[str, str]]] = []
    for f in md_files:
        if f.name == "index.md":
            continue
        fm = parse_front_matter(f)
        rel = str(f.relative_to(ROOT))
        if fm is None:
            print(f"  ⚠ {rel}: no front matter — skipped", file=sys.stderr)
            continue
        rows.append((rel, fm))

    if not rows:
        print("No files with front matter found", file=sys.stderr)
        sys.exit(1)

    html = render_html(rows)
    OUTPUT.write_text(html)
    print(f"Wrote {OUTPUT} ({len(rows)} row(s))")


if __name__ == "__main__":
    main()
