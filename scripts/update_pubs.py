"""Query NASA ADS and write CV-ready LaTeX publication lists.

Outputs (in ``pubs/``), each in reverse chronological order:

    all.tex                    every paper, full author list
    00_unsorted.tex            other 4th+ author refereed papers: add these to a library
    0_non_refereed.tex         everything else not refereed, mostly preprints (printed after each run)
    1_first_author.tex         1st-author refereed papers
    2_second_third_author.tex  2nd- and 3rd-author refereed papers
    3_as_collaborator.tex      4th+ author refereed papers in my "as collaborator" ADS library
    4_as_observer.tex          4th+ author refereed papers in my "as observer" ADS library
    5_tks.tex                  TESS-Keck Survey refereed papers (4th+ author)
    6_proceedings.tex          conference proceedings
    7_whitepapers.tex          white papers (e.g. Astro2020 in BAAS)
    other/thesis.tex           my PhD thesis
    other/zenodo.tex           Zenodo records
    other/vizier.tex           VizieR data catalogs
    other/code.tex             other software (e.g. ASCL entries)
    other/abstracts.tex        meeting abstracts
    papers.json                metadata (author position, citations, ...) for pub_stats.py
    cv_entries.json            entries for the CV sections, for prepare_cv.py

then runs prepare_cv.py to refresh the CV section files in pubs/for_cv/.

Finds and bolds my name wherever it appears; if the author list is truncated before
my name, a bold "(incl. RAR)" is inserted after the author list instead.

Needs an ADS API token, from https://ui.adsabs.harvard.edu/user/settings/token,
in the ADS_API_TOKEN environment variable (or in ~/.ads/dev_key).
"""

import argparse
import json
import os
import re
import sys
import tomllib
from pathlib import Path
from urllib.parse import quote

import requests

import prepare_cv

API = "https://api.adsabs.harvard.edu/v1"

# Name variants I publish under; papers matching any of these are included.
AUTHORS = ["Rubenzahl, Ryan A.", "Rubenzahl, Ryan"]
SURNAME = "Rubenzahl"

# Authors listed before "et al." when config.toml doesn't say; all.tex lists everyone.
MAX_AUTHORS = 10

# ADS custom export formats, used unless [format] in config.toml sets them
# (https://ui.adsabs.harvard.edu/help/actions/export). %AUTHORS is replaced by the
# author-list spec, e.g. %10.10o for 10 authors in author style "o".
AUTHOR_STYLE = "o"
CV_FORMAT = r"%ZEncoding:latex\cvitem{%Y}{%AUTHORS, ``{%T}'', \textit{%J}, %V, %p}\n"
# Not-yet-published preprints (ADS keeps the arXiv ID in the page field).
SUBMITTED_FORMAT = (
    r"%ZEncoding:latex\cvitem{%Y}{%AUTHORS, ``{%T}'', \textit{submitted}, %p}\n"
)
# Preprints placed by hand in CATEGORY_OVERRIDES: just the (linked) arXiv ID.
PREPRINT_FORMAT = r"%ZEncoding:latex\cvitem{%Y}{%AUTHORS, ``{%T}'', %p}\n"

# My hand-sorted ADS libraries (by name) for 4th+ author refereed papers.
LIBRARIES = {
    "3_as_collaborator": "Publications (as collaborator)",
    "4_as_observer": "Publications (as observer)",
}

# Titles matching this are TESS-Keck Survey papers.
# (Any separator, since some ADS titles use Unicode dashes, e.g. "TESS─Keck".)
TKS_PATTERN = re.compile(r"TESS\W?Keck Survey|\bTKS\b", re.IGNORECASE)

# Journals ADS doesn't flag as refereed that I list with refereed papers.
REFEREED_BIBSTEMS = {"RNAAS"}
# Papers to put in a specific list regardless of the rules below.
CATEGORY_OVERRIDES = {
    "2024arXiv240207893C": "5_tks",  # Chontos+ TKS XXI (preprint)
}
# Proceedings ADS files as (refereed) journal articles.
PROCEEDINGS_BIBCODES = {
    "2023AN....34430088K",  # Kassis+ Keck instrumentation status (proceedings)
}

# My given names as ADS prints them: "R.", "R.~A.", "Ryan", "Ryan A.".
GIVEN = r"(?:R\.|Ryan)(?:(?:~|\s+)A\.)?"
# My name in any ADS author style: "R.~A. Rubenzahl", "Rubenzahl, R.~A.",
# "Rubenzahl R.~A.", "Rubenzahl, Ryan A." or just "Rubenzahl".
NAME_PATTERN = re.compile(
    rf"(?<![\w.]){GIVEN}(?:~|\s+){SURNAME}\b|\b{SURNAME}\b(?:,?\s+{GIVEN})?"
)
INCL = r" \textbf{(incl. RAR)}"

# Unicode that ADS's LaTeX encoding leaves in place but pdflatex can't handle.
UNICODE_FIXES = {
    "\u2500": "-",
    "\u2010": "-",
    "\u2011": "-",
    "\u2013": "--",
    "\u2014": "---",
}

OUTDIR = Path(__file__).resolve().parent.parent / "pubs"
CONFIG = OUTDIR.parent / "config.toml"
JOURNALS = OUTDIR.parent / "journals.toml"


def get_token():
    token = os.environ.get("ADS_API_TOKEN") or os.environ.get("ADS_DEV_KEY")
    if token:
        return token.strip()
    keyfile = Path.home() / ".ads" / "dev_key"
    if keyfile.exists():
        return keyfile.read_text().strip()
    sys.exit("No ADS token: set ADS_API_TOKEN or write it to ~/.ads/dev_key")


def search(session):
    q = " OR ".join(f'author:"{a}"' for a in AUTHORS)
    r = session.get(
        f"{API}/search/query",
        params={
            "q": q,
            "fl": "bibcode,identifier,author,title,date,year,doctype,bibstem,pub,property,citation_count,doi",
            "rows": 2000,
            "sort": "date desc",
        },
    )
    r.raise_for_status()
    return r.json()["response"]["docs"]


def library_bibcodes(session):
    """{list name: set of bibcodes} for the ADS libraries in LIBRARIES."""
    r = session.get(f"{API}/biblib/libraries")
    r.raise_for_status()
    ids = {lib["name"]: lib["id"] for lib in r.json()["libraries"]}
    out = {}
    for name, lib in LIBRARIES.items():
        if lib not in ids:
            sys.exit(f"No ADS library named {lib!r}; found: {', '.join(sorted(ids))}")
        r = session.get(f"{API}/biblib/libraries/{ids[lib]}", params={"rows": 2000})
        r.raise_for_status()
        out[name] = set(r.json()["documents"])
    return out


def assign_libraries(docs, libraries):
    """Tag each doc with the library list it's in (matching any of its bibcodes)."""
    for doc in docs:
        ids = {doc["bibcode"], *doc.get("identifier", [])}
        for name, bibcodes in libraries.items():
            if ids & bibcodes:
                doc["library"] = name
                break


def author_position(doc):
    """1-indexed position of my name in the author list (0 if not found)."""
    for i, name in enumerate(doc.get("author", []), 1):
        if name.startswith(SURNAME + ","):
            return i
    return 0


def is_submitted(doc):
    """Preprint with no journal version yet (ADS merges them once published)."""
    return doc.get("doctype") == "eprint" or "arXiv" in doc.get("bibstem", [])


def is_refereed(doc):
    # ADS flags theses as refereed, but they aren't refereed papers.
    if doc["bibcode"] in PROCEEDINGS_BIBCODES or doc.get("doctype") == "phdthesis":
        return False
    if REFEREED_BIBSTEMS & set(doc.get("bibstem", [])):
        return True
    return "REFEREED" in doc.get("property", [])


def is_tks(doc):
    return bool(TKS_PATTERN.search(" ".join(doc.get("title", []))))


def category(doc):
    """Which CV list a paper goes in (the first one it qualifies for)."""
    if doc["bibcode"] in CATEGORY_OVERRIDES:
        return CATEGORY_OVERRIDES[doc["bibcode"]]
    if doc.get("doctype") == "phdthesis":
        return "other/thesis"
    bibstem = doc.get("bibstem", [])
    if "zndo" in bibstem:
        return "other/zenodo"
    if "yCat" in bibstem:
        return "other/vizier"
    if "ascl" in bibstem or doc.get("doctype") == "software":
        return "other/code"
    if doc.get("doctype") == "abstract":
        return "other/abstracts"
    if not is_refereed(doc):
        if (
            doc.get("doctype") == "inproceedings"
            or doc["bibcode"] in PROCEEDINGS_BIBCODES
        ):
            return "6_proceedings"
        title = " ".join(doc.get("title", []))
        if "BAAS" in bibstem or re.search(r"white\s*paper", title, re.IGNORECASE):
            return "7_whitepapers"
        return "0_non_refereed"
    pos = author_position(doc)
    if pos == 1:
        return "1_first_author"
    if pos in (2, 3):
        return "2_second_third_author"
    if "library" in doc:
        return doc["library"]
    if is_tks(doc):
        return "5_tks"
    return "00_unsorted"


def categorize(docs):
    names = [
        "00_unsorted",
        "0_non_refereed",
        "1_first_author",
        "2_second_third_author",
        "3_as_collaborator",
        "4_as_observer",
        "5_tks",
        "6_proceedings",
        "7_whitepapers",
        "other/thesis",
        "other/zenodo",
        "other/vizier",
        "other/code",
        "other/abstracts",
    ]
    groups = {name: [] for name in names}
    for doc in docs:
        groups[category(doc)].append(doc["bibcode"])
    return groups


def save_records(docs):
    """Write the paper metadata to papers.json, for pub_stats.py."""
    records = [
        {
            "bibcode": d["bibcode"],
            "year": d.get("year"),
            "doctype": d.get("doctype"),
            "title": " ".join(d.get("title", [])),
            "author_position": author_position(d),
            "n_authors": len(d.get("author", [])),
            "citations": d.get("citation_count", 0),
            "refereed": is_refereed(d),
            "submitted": is_submitted(d),
            "tks": is_tks(d),
            "category": category(d),
        }
        for d in docs
    ]
    path = OUTDIR / "papers.json"
    path.write_text(json.dumps(records, indent=2) + "\n")
    print(f"{len(records):4d}  {path.relative_to(OUTDIR.parent)}")


def export(session, bibcodes, fmt):
    """Format bibcodes with an ADS custom format; returns {bibcode: entry}."""
    if not bibcodes:
        return {}
    # Prefix each entry with its bibcode so entries can be matched back up.
    enc = "%ZEncoding:latex"
    fmt = fmt.replace(enc, enc + "%R|", 1) if enc in fmt else "%R|" + fmt
    r = session.post(
        f"{API}/export/custom",
        json={"bibcode": bibcodes, "format": fmt, "sort": "date desc"},
    )
    r.raise_for_status()
    entries = {}
    for line in r.json()["export"].splitlines():
        if "|" in line:
            bibcode, entry = line.split("|", 1)
            entries[bibcode.strip().replace(r"\&", "&")] = entry
    return entries


def href_url(url):
    """Escape a URL for use in \\href."""
    return url.replace("%", r"\%").replace("#", r"\#")


def ads_url(doc):
    return f"https://ui.adsabs.harvard.edu/abs/{quote(doc['bibcode'])}/abstract"


def load_abbreviations():
    """journals.toml ({"journals": ..., "bibstems": ...}), if custom_abbreviations is on."""
    if not load_config().get("format", {}).get("custom_abbreviations", False):
        return {}
    return tomllib.loads(JOURNALS.read_text())


def abbreviate(entry, doc, abbreviations):
    """Swap the journal name after the title for its abbreviation, if it has one."""
    pub = doc.get("pub", "")
    journals = abbreviations.get("journals", {})
    bibstems = abbreviations.get("bibstems", {})
    # "...Meeting Abstracts #243" uses the entry for "...Meeting Abstracts".
    base, number = re.fullmatch(r"(.*?)((?:\s*#\d+)?)", pub).groups()
    stem = next((b for b in doc.get("bibstem", []) if b in bibstems), None)
    if pub in journals:
        abbr = journals[pub]
    elif base in journals:
        abbr = journals[base] + number.replace("#", r"\#")
    elif stem:
        abbr = bibstems[stem]
    else:
        return entry
    name = pub.replace("&", r"\&").replace("#", r"\#")
    title_end = entry.find("}''") + 3
    return entry[:title_end] + entry[title_end:].replace(name, abbr, 1)


def add_links(entry, doc, abbreviations=None):
    """Link the title to the DOI (or ADS) and append a linked citation count."""
    if abbreviations:
        entry = abbreviate(entry, doc, abbreviations)
    # Drop dangling commas left by empty fields (e.g. a thesis has no volume or page).
    entry = re.sub(r"(,\s*)+}\s*$", "}", entry)
    for char, tex in UNICODE_FIXES.items():
        entry = entry.replace(char, tex)
    doi = doc.get("doi")
    url = (
        href_url("https://doi.org/" + quote(doi[0], safe="/:;()"))
        if doi
        else href_url(ads_url(doc))
    )
    start = entry.find("``{")
    end = entry.find("}''", start)
    if start >= 0 and end >= 0:
        title = entry[start + 3 : end]
        entry = entry[:start] + rf"``\href{{{url}}}{{{title}}}''" + entry[end + 3 :]
    entry = re.sub(
        r"arXiv:(\d{4}\.\d{4,5})", r"\\href{https://arxiv.org/abs/\1}{arXiv:\1}", entry
    )
    n = doc.get("citation_count") or 0
    if n:
        cites = rf" [\href{{{href_url(ads_url(doc))}}}{{{n} citation{'s' if n > 1 else ''}}}]"
        entry = entry[: entry.rindex("}")] + cites + "}"
    return entry


def export_format(doc):
    """Which [format] entry a paper uses."""
    if not is_submitted(doc):
        return "published"
    if doc["bibcode"] in CATEGORY_OVERRIDES:
        return "preprint"
    return "submitted"


def load_formats():
    """(author style, {format name: ADS format}) from config.toml, with defaults."""
    config = load_config().get("format", {})
    formats = {
        "published": CV_FORMAT,
        "submitted": SUBMITTED_FORMAT,
        "preprint": PREPRINT_FORMAT,
    }
    return config.get("author_style", AUTHOR_STYLE), {
        k: config.get(k, v) for k, v in formats.items()
    }


def format_all(session, docs, max_authors):
    """{bibcode: entry}, labeling unpublished preprints as submitted."""
    style, formats = load_formats()
    groups = {}
    for d in docs:
        groups.setdefault(export_format(d), []).append(d["bibcode"])
    entries = {}
    for name, bibcodes in groups.items():
        fmt = formats[name].replace("%AUTHORS", f"%{max_authors}.{max_authors}{style}")
        entries |= export(session, bibcodes, fmt)
    abbreviations = load_abbreviations()
    return {
        d["bibcode"]: add_links(entries[d["bibcode"]], d, abbreviations) for d in docs
    }


def highlight(entry):
    """Bold my name, or flag that I'm hidden in the 'et al.'."""
    entry, n = NAME_PATTERN.subn(lambda m: rf"\textbf{{{m.group(0)}}}", entry)
    if n:
        return entry
    # Insert right after the author list (i.e., before the quoted title).
    idx = entry.find(", ``")
    if idx < 0:
        return entry.rstrip().rstrip("}") + INCL + "}"
    return entry[:idx] + INCL + entry[idx:]


def write(name, entries):
    path = OUTDIR / f"{name}.tex"
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n".join(highlight(e) for e in entries) + "\n")
    print(f"{len(entries):4d}  {path.relative_to(OUTDIR.parent)}")


def load_config():
    return tomllib.loads(CONFIG.read_text()) if CONFIG.exists() else {}


def max_authors_per_list(names, override=None):
    """{list name: authors to show}, from config.toml unless overridden."""
    limits = load_config().get("max_authors", {})
    default = limits.get("default", MAX_AUTHORS)
    return {name: override or limits.get(name, default) for name in names}


def max_authors_per_section(list_limits, override=None):
    """{(CV section, list name): authors to show} for the pubs/for_cv/ sections.

    Uses [cv_max_authors] in config.toml, falling back to each list's own limit.
    """
    limits = load_config().get("cv_max_authors", {})
    out = {}
    for section, names in prepare_cv.SECTIONS.items():
        n = limits.get(section.removesuffix(".tex"), limits.get("default"))
        for name in names:
            out[section, name] = override or n or list_limits[name]
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--maxauthors",
        type=int,
        help="authors listed before 'et al.' in every list, overriding config.toml",
    )
    args = parser.parse_args()

    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {get_token()}"

    docs = search(session)
    assign_libraries(docs, library_bibcodes(session))
    OUTDIR.mkdir(exist_ok=True)
    save_records(docs)

    # docs are newest first, and the lists keep that order.
    full = format_all(session, docs, max_authors=5000)
    write("all", [full[d["bibcode"]] for d in docs])
    groups = categorize(docs)
    limits = max_authors_per_list(groups, args.maxauthors)
    by_bibcode = {d["bibcode"]: d for d in docs}
    cv_limits = max_authors_per_section(limits, args.maxauthors)
    # One set of exports per author limit, each covering the papers that use it.
    needed = {}
    for name, n in limits.items():
        needed.setdefault(n, set()).update(groups[name])
    for (_, name), n in cv_limits.items():
        needed.setdefault(n, set()).update(groups[name])
    formatted = {
        n: format_all(session, [d for d in docs if d["bibcode"] in bibcodes], n)
        for n, bibcodes in needed.items()
    }
    for name, bibcodes in groups.items():
        write(name, [formatted[limits[name]][b] for b in bibcodes])

    # Entries for the CV sections, for prepare_cv.py.
    cv_entries = {}
    for (section, name), n in cv_limits.items():
        for b in groups[name]:
            cv_entries.setdefault(section, {})[b] = highlight(formatted[n][b])
    (OUTDIR / "cv_entries.json").write_text(json.dumps(cv_entries, indent=2) + "\n")

    def print_links(bibcodes):
        for b in bibcodes:
            doc = by_bibcode[b]
            print(f"  {ads_url(doc)}  {' '.join(doc.get('title', []))[:70]}")

    if groups["00_unsorted"]:
        libraries = " / ".join(LIBRARIES.values())
        print(f"\nUnsorted papers: add to an ADS library ({libraries}) and rerun:")
        print_links(groups["00_unsorted"])

    print("\nCV sections:")
    prepare_cv.main()

    if groups["0_non_refereed"]:
        stars = "*" * 80
        print(
            f"\n{stars}\nNon-refereed (possibly submitted): move by hand if submitted:"
        )
        print_links(groups["0_non_refereed"])
        print(stars)


if __name__ == "__main__":
    main()
