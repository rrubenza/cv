#!/usr/bin/env python3
"""Summarize citations/h-index based on pubs/papers.json

Run scripts/update_pubs.py first to refresh papers.json from ADS.
Prints paper counts, citation counts and h-index by author position
(and a few other cuts) and writes the same table to pubs/stats.txt.
"""

import json
from pathlib import Path

PUBS = Path(__file__).resolve().parent.parent / "pubs"

# List counts by author position up to MAX_POSITION,
# then summarizes all papers with author position > MAX_POSITION
# in the "MAX_POSITION+1+ author" row.
MAX_POSITION = 3


def ordinal(n):
    suffix = (
        "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    )
    return f"{n}{suffix}"


def h_index(papers):
    cites = sorted((p["citations"] for p in papers), reverse=True)
    return sum(c >= i for i, c in enumerate(cites, 1))


def rows(papers):
    yield "All papers", papers
    for n in range(1, MAX_POSITION + 1):
        yield f"{ordinal(n)} author", [p for p in papers if p["author_position"] == n]
    yield (
        f"{ordinal(MAX_POSITION + 1)}+ author",
        [p for p in papers if p["author_position"] > MAX_POSITION],
    )
    unknown = [p for p in papers if p["author_position"] == 0]
    if unknown:
        yield "Name not in author list", unknown
    yield "TESS-Keck Survey", [p for p in papers if p["tks"]]
    yield "Submitted (preprints)", [p for p in papers if p["submitted"]]


def table(papers):
    columns = ["Papers", "Citations", "h-index", "Refereed", "Ref. cites", "Ref. h"]
    header = f"{'':<24}" + "".join(f"{c:>11}" for c in columns)
    lines = [header, "-" * len(header)]
    for label, group in rows(papers):
        refereed = [p for p in group if p["refereed"]]
        values = [
            len(group),
            sum(p["citations"] for p in group),
            h_index(group),
            len(refereed),
            sum(p["citations"] for p in refereed),
            h_index(refereed),
        ]
        lines.append(f"{label:<24}" + "".join(f"{v:>11}" for v in values))
    return "\n".join(lines)


def main():
    path = PUBS / "papers.json"
    if not path.exists():
        raise SystemExit(f"{path} not found; run scripts/update_pubs.py first")
    out = table(json.loads(path.read_text()))
    print(out)
    (PUBS / "stats.txt").write_text(out + "\n")


if __name__ == "__main__":
    main()
