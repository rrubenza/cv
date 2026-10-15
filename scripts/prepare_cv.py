"""Generate the CV-ready formatted lists in pubs/for_cv/. These are for
copying into my CV overleaf project, to then import into the document.

Each section file keeps its hand-written header, all entries with a {year} field
are then replaced with the updated list in reverse chronological order. Also
updates teh citation count in the subsection title, and stamps the file
with a "%% Last updated: ..." line.

Runs automatically at the end of scripts/update_pubs.py;
Can also run this script directly to e.g. redo with config settings changed.
"""

import json
import re
from datetime import date
from pathlib import Path

PUBS = Path(__file__).resolve().parent.parent / "pubs"
CV_DIR = PUBS / "for_cv"

# CV section files (in for_cv/)
# Number of authors printed comes from [cv_max_authors] in config.toml.
SECTIONS = {
    "selectedpubs.tex": ["1_first_author", "2_second_third_author"],
    "ascollaborator.tex": ["3_as_collaborator"],
    "asobserver.tex": ["4_as_observer"],
    "TKS.tex": ["5_tks"],
    "proceedings.tex": ["6_proceedings"],
}

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


# Summary lines printed to copy-paste into the CV Publications section header
SUMMARIES = {
    "Refereed": [
        "1_first_author",
        "2_second_third_author",
        "3_as_collaborator",
        "4_as_observer",
        "5_tks",
        "00_unsorted",
    ],
    "Non-Refereed": ["6_proceedings"],
}
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


def main():
    config = PUBS.parent / "config.toml"
    if (
        config.exists()
        and config.stat().st_mtime > (PUBS / "cv_entries.json").stat().st_mtime
    ):
        print(
            "Warning: config.toml changed since the last update_pubs.py run;\n"
            "Rerun update_pubs.py to apply the new settings.\n"
        )
    sections = load_entries()
    for filename in SECTIONS:
        path = CV_DIR / filename
        if not path.exists():
            print(f"skipping {path.relative_to(PUBS.parent)}: no such file")
            continue
        update_section(path, sections.get(filename, []))

    records = json.loads((PUBS / "papers.json").read_text())
    print("\nSummary lines for the CV:")
    for label, names in SUMMARIES.items():
        print(summary_line(label, [r for r in records if r["category"] in names]))
    today = date.today()
    total = sum(r["citations"] for r in records)
    # Small comment for my own personal history tracking
    when = ["early", "mid", "late"][(today.month - 1) // 4]
    print(f"%h-index: {h_index(records)} ({total:,} citations) -- {when} {today.year}")


if __name__ == "__main__":
    main()
