"""Generate the CV-ready formatted lists in cv/publists/, for copying into a CV.

Which lists go into which section file is set by [cv_sections] in config.toml.
Each section file keeps its hand-written header, all entries with a {year} field
are then replaced with the updated list in reverse chronological order. Also
updates the citation count in the subsection title, and stamps the file
with a "%% Last updated: ..." line. Missing section files are created with a
minimal \\subsection header to edit.

Runs automatically at the end of scripts/update_pubs.py;
Can also run this script directly to e.g. redo with config settings changed.
"""

import argparse
import json
import re
import shutil
import subprocess
import tomllib
from datetime import date
from pathlib import Path

PUBS = Path(__file__).resolve().parent.parent / "pubs"
CV_DIR = PUBS.parent / "cv" / "publists"
DOCUMENT = CV_DIR.parent / "publication_list.tex"

# Starter moderncv preamble for cv/publication_list.tex, used when the file has no
# \begin{document} yet. After that, everything up to \begin{document} is yours to
# edit (e.g. paste in your CV's preamble) and is kept on every run.
PREAMBLE = r"""\documentclass[11pt,letterpaper,sans]{moderncv}
\moderncvstyle{banking}
\moderncvcolor{blue}
\usepackage[T1]{fontenc}
\usepackage[scale=0.85]{geometry}

\name{FIRST}{LAST}
"""
BEGIN = r"\begin{document}"
HINDEX = re.compile(r"^%h-index:.*$", re.MULTILINE)
CONFIG = PUBS.parent / "config.toml"


def load_config():
    return tomllib.loads(CONFIG.read_text()) if CONFIG.exists() else {}


def sections():
    """[cv_sections] from config.toml: {section file: [lists merged into it]}."""
    return load_config().get("cv_sections", {})


def summaries():
    """[cv_summary] from config.toml: {label: [lists counted in that line]}."""
    return load_config().get(
        "cv_summary",
        {
            "Refereed": ["1_first_author", "2_second_third_author", "3_nth_author"],
            "Non-Refereed": ["4_proceedings"],
        },
    )


FIRST_ENTRY = re.compile(r"^[ \t]*\\cvitem\{\d{4}\}", re.MULTILINE)
LAST_UPDATED = re.compile(r"^%*\s*Last updated:.*", re.MULTILINE)
SUBSECTION = re.compile(r"\\subsection\{([^{}]*?)(?: \([\d,]+ citations?\))?\}")


def load_entries():
    """{section: [(index, record, entry)]}, where index is the paper's date rank."""
    records = json.loads((PUBS / "papers.json").read_text())
    rank = {r["bibcode"]: (i, r) for i, r in enumerate(records)}
    # Written by update_pubs.py, using the [cv_max_authors] limits in config.toml.
    entries = json.loads((PUBS / "cv_entries.json").read_text())
    return {
        section: [(*rank[b], entry) for b, entry in section_entries.items()]
        for section, section_entries in entries.items()
    }


def citation_label(n):
    return f"({n:,} citation{'' if n == 1 else 's'})"


def update_section(path, items):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rf"\subsection{{{path.stem}}}" + "\n")
        print(f"created {path.relative_to(PUBS.parent)}; edit its header as you like")
    text = path.read_text()
    match = FIRST_ENTRY.search(text)
    header = (text[: match.start()] if match else text).rstrip("\n")
    cites = citation_label(sum(r["citations"] for _, r, _ in items))
    today = date.today()
    stamp = f"%% Last updated: {today:%b} {today.day}, {today.year}"
    header, n = LAST_UPDATED.subn(stamp, header)
    if not n:
        header += "\n\n" + stamp
    header = SUBSECTION.sub(
        lambda m: rf"\subsection{{{m.group(1)} {cites}}}", header, count=1
    )
    entries = [entry for _, _, entry in sorted(items, key=lambda item: item[0])]
    path.write_text(header + "\n" + "\n\n".join(entries) + "\n")
    print(f"{len(entries):4d}  {path.relative_to(PUBS.parent)}  {cites}")


# Author-position groups in each summary line.
AUTHOR_GROUPS = {
    "first author": lambda pos: pos == 1,
    "second/third author": lambda pos: pos in (2, 3),
    "nth author": lambda pos: pos not in (1, 2, 3),
}


def summary_line(label, records):
    """\\cvitem summarizing paper and citation counts by author position."""
    parts = []
    for group_label, in_group in AUTHOR_GROUPS.items():
        group = [r for r in records if in_group(r["author_position"])]
        cites = citation_label(sum(r["citations"] for r in group))
        parts.append(f"{len(group)} {group_label} {cites}")
    return rf"\cvitem{{{label}}}{{{', '.join(parts)}}}{{}}"


def h_index(records):
    cites = sorted((r["citations"] for r in records), reverse=True)
    return sum(c >= i for i, c in enumerate(cites, 1))


def hindex_line(records):
    """'%h-index: 24 (2,268 citations) -- late 2026' (early/mid/late = 4-month thirds)."""
    today = date.today()
    total = sum(r["citations"] for r in records)
    when = ["early", "mid", "late"][(today.month - 1) // 4]
    return f"%h-index: {h_index(records)} ({total:,} citations) -- {when} {today.year}"


def write_document(lines_by_label, hindex):
    """Write cv/publication_list.tex from [cv_document] in config.toml.

    The preamble (everything up to \\begin{document}) is kept as is; the body is
    regenerated. Entries starting with "#" are written commented out. Earlier
    %h-index lines are kept below the new one (replacing one from the same period).
    """
    doc = load_config().get("cv_document")
    if not doc:
        return

    def entry(name, text):
        return f"% {text}" if name.startswith("#") else text

    text = DOCUMENT.read_text() if DOCUMENT.exists() else ""
    if BEGIN in text:
        preamble = text[: text.index(BEGIN)].rstrip("\n")
    else:
        name = load_config().get("author", {})
        preamble = (
            PREAMBLE.replace("FIRST", name.get("first", "First"))
            .replace("LAST", name.get("last", "Last"))
            .rstrip("\n")
        )
        print(
            f"Added a starter preamble to {DOCUMENT.relative_to(PUBS.parent)}; edit as you like"
        )
    history = HINDEX.findall(text)
    period = hindex.rsplit(" -- ", 1)[-1]
    history = [h for h in history if not h.rstrip().endswith(period)]
    lines = [
        preamble,
        "",
        BEGIN,
        "%% Below is generated by scripts/prepare_cv.py from [cv_document] in config.toml.",
        rf"\section{{{doc.get('title', 'Publications')}}}",
        "",
        *(entry(n, lines_by_label[n.lstrip("#")]) for n in doc.get("summaries", [])),
        hindex,
        *history,
        "",
        *(
            entry(n, rf"\input{{publists/{n.lstrip('#')}}}")
            for n in doc.get("sections", [])
        ),
        "",
        r"\end{document}",
    ]
    DOCUMENT.write_text("\n".join(lines) + "\n")
    print(f"\nWrote {DOCUMENT.relative_to(PUBS.parent)}")


def compile_pdf():
    """Compile cv/publication_list.tex to cv/publication_list.pdf."""
    if not shutil.which("latexmk"):
        print("latexmk not found; skipping the PDF")
        return
    build = DOCUMENT.parent / "build"
    result = subprocess.run(
        ["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error",
         f"-outdir={build}", DOCUMENT.name],
        cwd=DOCUMENT.parent, capture_output=True, text=True,
    )  # fmt: skip
    pdf = build / DOCUMENT.with_suffix(".pdf").name
    if result.returncode or not pdf.exists():
        log = build / DOCUMENT.with_suffix(".log").name
        print(f"LaTeX failed; see {log.relative_to(PUBS.parent)}")
        return
    shutil.copy(pdf, DOCUMENT.with_suffix(".pdf"))
    print(f"Wrote {DOCUMENT.with_suffix('.pdf').relative_to(PUBS.parent)}")


def main(pdf=False):
    if (
        CONFIG.exists()
        and CONFIG.stat().st_mtime > (PUBS / "cv_entries.json").stat().st_mtime
    ):
        print(
            "Warning: config.toml changed since the last update_pubs.py run;\n"
            "Rerun update_pubs.py to apply the new settings.\n"
        )
    entries = load_entries()
    for filename in sections():
        update_section(CV_DIR / filename, entries.get(filename, []))

    records = json.loads((PUBS / "papers.json").read_text())
    lines_by_label = {
        label: summary_line(label, [r for r in records if set(names) & set(r["lists"])])
        for label, names in summaries().items()
    }
    hindex = hindex_line(records)
    print("\nSummary lines for the CV:")
    print("\n".join([*lines_by_label.values(), hindex]))

    write_document(lines_by_label, hindex)
    if pdf:
        compile_pdf()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--pdf", action="store_true", help="also compile cv/publication_list.pdf"
    )
    parser.add_argument(
        "--pdf-only",
        action="store_true",
        help="only compile cv/publication_list.pdf, without rewriting any files",
    )
    args = parser.parse_args()
    if args.pdf_only:
        compile_pdf()
    else:
        main(pdf=args.pdf)
