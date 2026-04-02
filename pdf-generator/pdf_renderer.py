"""
pdf_renderer.py — Converts HTML → PDF using WeasyPrint.
Post-processes with PyMuPDF to add "CONTINUED - " prefix on section
headers that repeat across page breaks.
"""

import sys
import os
import json
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent


def _add_continued_headers(pdf_path: str, estimate_path: str = None):
    """
    Post-process PDF: find section headers that repeat on continuation pages
    and prefix them with 'CONTINUED - '.
    """
    try:
        import fitz
    except ImportError:
        print("[pdf_renderer] PyMuPDF not available — skipping CONTINUED headers")
        return

    # Load section names from estimate JSON
    section_names = []
    if estimate_path and os.path.exists(estimate_path):
        with open(estimate_path) as f:
            estimate = json.load(f)
        section_names = [s['name'] for s in estimate.get('sections', [])]
    
    if not section_names:
        return

    doc = fitz.open(pdf_path)
    section_first_page = {}
    fixes = 0

    for page_num in range(len(doc)):
        page = doc[page_num]
        text_blocks = page.get_text("dict")["blocks"]
        for block in text_blocks:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span["text"].strip()
                    size = span["size"]
                    flags = span["flags"]
                    is_bold = flags & (1 << 4)
                    bbox = fitz.Rect(span["bbox"])

                    if not is_bold or size < 10 or size > 13:
                        continue

                    for sname in section_names:
                        if text == sname:
                            # Verify this line only contains the section name
                            line_text = "".join(s["text"] for s in line["spans"]).strip()
                            if line_text != sname:
                                continue

                            if sname not in section_first_page:
                                section_first_page[sname] = page_num
                            elif page_num > section_first_page[sname]:
                                page.draw_rect(bbox, color=None, fill=(1, 1, 1))
                                page.insert_text(
                                    (bbox.x0, bbox.y1 - 1),
                                    f"CONTINUED - {sname}",
                                    fontsize=span["size"],
                                    fontname="Times-Bold",
                                    color=(0, 0, 0)
                                )
                                fixes += 1

    if fixes:
        doc.save(pdf_path, incremental=True, encryption=0)
        print(f"[pdf_renderer] Added CONTINUED prefix to {fixes} section header(s)")
    doc.close()


def render(html_path: str, output_path: str, estimate_json_path: str = None) -> str:
    """
    Convert HTML file → PDF, then post-process for CONTINUED headers.
    Returns path to PDF file.
    """
    # Use venv WeasyPrint if available, otherwise fall back to system
    venv_python = Path(__file__).parent / ".venv" / "bin" / "python"

    try:
        from weasyprint import HTML, CSS
        print(f"[pdf_renderer] Rendering HTML → PDF...")
        html = HTML(filename=html_path)
        html.write_pdf(output_path)
        print(f"[pdf_renderer] PDF written to {output_path}")

    except ImportError:
        import subprocess
        script = f"""
import sys
sys.path.insert(0, '{str(Path(__file__).parent / ".venv" / "lib")}')
from weasyprint import HTML
HTML(filename='{html_path}').write_pdf('{output_path}')
print("done")
"""
        result = subprocess.run(
            [str(venv_python), "-c", script],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"WeasyPrint failed: {result.stderr}")
        print(f"[pdf_renderer] PDF written to {output_path}")

    # Auto-detect estimate JSON if not provided
    if not estimate_json_path:
        # Try to find matching estimate JSON from the output filename
        stem = Path(output_path).stem  # e.g. "DOYLE_IFC Supp 9.0"
        prefix = stem.split("_")[0]  # e.g. "DOYLE"
        candidate = WORKSPACE / f"{prefix}_estimate.json"
        if candidate.exists():
            estimate_json_path = str(candidate)

    # Post-process: add CONTINUED headers
    _add_continued_headers(output_path, estimate_json_path)

    return output_path


if __name__ == "__main__":
    html_path = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).parent / "estimate.html")
    output_path = str(Path(html_path).with_suffix(".pdf"))
    render(html_path, output_path)
    print(f"Done: {output_path}")
