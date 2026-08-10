#!/usr/bin/env python3
"""Render Final_Report.md -> Final_Report.pdf with gutenberg.css.

Mirrors md2pdf's pipeline (same markdown extensions) but passes a
weasyprint FontConfiguration so @font-face rules (Google Fonts) work.
"""

import sys
from pathlib import Path

from markdown import markdown
from weasyprint import CSS, HTML
from weasyprint.text.fonts import FontConfiguration

HERE = Path(__file__).resolve().parent
MD = HERE / "Final_Report.md"
CSS_FILE = HERE / "gutenberg.css"
PDF = HERE / "Final_Report.pdf"

EXTENSIONS = [
    "markdown.extensions.tables",
    "pymdownx.magiclink",
    "pymdownx.betterem",
    "pymdownx.superfences",
]


def main() -> int:
    """Render the markdown report to PDF and print the result."""
    raw = MD.read_text()
    raw_html = markdown(raw, extensions=EXTENSIONS)

    font_config = FontConfiguration()
    html = HTML(string=raw_html, base_url=str(HERE))
    html.write_pdf(
        str(PDF),
        stylesheets=[CSS(filename=str(CSS_FILE), font_config=font_config)],
        font_config=font_config,
    )
    print(f"OK: {PDF} ({PDF.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
