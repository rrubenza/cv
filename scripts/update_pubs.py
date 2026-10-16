"""Query NASA ADS and write CV-ready LaTeX publication lists.

Everything specific to one person (name, ORCID, ADS libraries, overrides, CV
sections) is set in config.toml. Outputs (in ``pubs/``), each in reverse
chronological order:

    all.tex                    every paper, full author list
    00_unsorted.tex            4th+ author refereed papers matching no [[nth_author]] rule
    0_non_refereed.tex         everything else not refereed, mostly preprints (printed after each run)
    1_first_author.tex         1st-author refereed papers
    2_second_third_author.tex  2nd- and 3rd-author refereed papers
    3_nth_author.tex           4th+ author refereed papers (all of them)
    3.x_....tex                the [[nth_author]] sub-lists of 3_nth_author
    4_proceedings.tex          conference proceedings
    5_whitepapers.tex          white papers (e.g. Astro2020 in BAAS)
    other/thesis.tex           PhD thesis
    other/zenodo.tex           Zenodo records
    other/vizier.tex           VizieR data catalogs
    other/code.tex             other software (e.g. ASCL entries)
    other/abstracts.tex        meeting abstracts
    papers.json                metadata (author position, citations, ...) for pub_stats.py
    cv_entries.json            entries for the CV sections, for prepare_cv.py
    missing_orcid.md           papers where ADS doesn't link your ORCID (if orcid is set)

then runs prepare_cv.py to refresh the CV section files in cv/publists/.

Finds and bolds your name wherever it appears; if the author list is truncated
before your name, a bold "(incl. XYZ)" with your initials is inserted instead.

Needs an ADS API token, from https://ui.adsabs.harvard.edu/user/settings/token,
in the ADS_API_TOKEN environment variable (or in ~/.ads/dev_key).
"""

import argparse
import functools
import json
import os
import re
import sys
import tomllib
import unicodedata
from pathlib import Path
from urllib.parse import quote

import prepare_cv
import requests

API = "https://api.adsabs.harvard.edu/v1"

OUTDIR = Path(__file__).resolve().parent.parent / "pubs"
CONFIG = OUTDIR.parent / "config.toml"
JOURNALS = OUTDIR.parent / "journals.toml"

# Built-in lists. The [[nth_author]] sub-lists in config.toml are added to these.
UNSORTED = "00_unsorted"
NON_REFEREED = "0_non_refereed"
FIRST = "1_first_author"
SECOND_THIRD = "2_second_third_author"
NTH = "3_nth_author"
PROCEEDINGS = "4_proceedings"
WHITEPAPERS = "5_whitepapers"
OTHER = [
    "other/thesis",
    "other/zenodo",
    "other/vizier",
    "other/code",
    "other/abstracts",
]

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
# Preprints placed by hand in [overrides]: just the (linked) arXiv ID.
PREPRINT_FORMAT = r"%ZEncoding:latex\cvitem{%Y}{%AUTHORS, ``{%T}'', %p}\n"

# Unicode that ADS's LaTeX encoding leaves in place but pdflatex can't handle.
UNICODE_FIXES = {
    "\u2500": "-",
    "\u2010": "-",
    "\u2011": "-",
    "\u2013": "--",
    "\u2014": "---",
}

# Combining accents -> LaTeX accent commands, to match names as ADS prints them
# (e.g. "Stef{\'a}nsson", "Mo{\v{c}}nik").
ACCENTS = {
    "\u0301": "'", "\u0300": "`", "\u0308": '"', "\u0302": "^", "\u0303": "~",
    "\u0304": "=", "\u0307": ".", "\u030c": "v", "\u0327": "c", "\u030a": "r",
    "\u0306": "u", "\u030b": "H", "\u0328": "k",
}  # fmt: skip


@functools.cache
def load_config():
    return tomllib.loads(CONFIG.read_text()) if CONFIG.exists() else {}


# --- The author -----------------------------------------------------------------


@functools.cache
def author():
    """[author] from config.toml: first, middle, last, suffix, orcid, initials."""
    a = dict(load_config().get("author", {}))
    if not a.get("first") or not a.get("last"):
        sys.exit("Set your name in config.toml: [author] first = ..., last = ...")
    a["middles"] = a.get("middle", "").split()
    a["suffix"] = a.get("suffix", "").strip()
    if not a.get("initials"):
        initials = "".join(w[0] for w in [a["first"], *a["middles"], a["last"]])
        a["initials"] = initials + a["suffix"]
    return a


def tex(text):
    """LaTeX-encode accented letters the way ADS's latex export does."""
    out = ""
    for ch in unicodedata.normalize("NFD", text):
        if ch in ACCENTS and out:
            cmd, base = ACCENTS[ch], out[-1]
            out = out[:-1] + (
                rf"{{\{cmd}{{{base}}}}}" if cmd.isalpha() else rf"{{\{cmd}{base}}}"
            )
        else:
            out += ch
    return out


def initial(word):
    """'Ryan' -> 'R.', 'Jean-Luc' -> 'J.-L.', 'A.' -> 'A.'"""
    return "-".join(part[0] + "." for part in word.split("-"))


@functools.cache
def name_pattern():
    """Your name in any ADS author style, e.g. "R.~A. Rubenzahl", "Rubenzahl, R.~A.",
    "Rubenzahl R.~A.", "Rubenzahl, Ryan A." or just "Rubenzahl"."""
    a = author()
    sep = r"(?:~|\s+)"

    def word(w):
        return (
            "(?:"
            + "|".join(sorted({re.escape(tex(w)), re.escape(tex(initial(w)))}))
            + ")"
        )

    given = word(a["first"]) + "".join(f"(?:{sep}{word(m)})?" for m in a["middles"])
    last = re.escape(tex(a["last"]))
    if a["suffix"]:  # e.g. "Palumbo, III" or "Palumbo III", when ADS keeps it
        last += rf"(?:,?\s+{re.escape(a['suffix'])}(?![\w]))?"
    return re.compile(
        rf"(?<![\w.]){given}{sep}{last}(?![\w])|(?<![\w]){last}(?![\w])(?:,?\s+{given})?"
    )


def incl_marker():
    return rf" \textbf{{(incl. {author()['initials']})}}"


def query():
    """ADS query for your papers: your name (ADS also matches its abbreviations),
    plus your ORCID if set."""
    a = author()
    names = {
        f"{a['last']}, {' '.join([a['first'], *a['middles']])}",
        f"{a['last']}, {a['first']}",
    }
    q = " OR ".join(f'author:"{n}"' for n in sorted(names))
    if a.get("orcid"):
        q += f' OR orcid:"{a["orcid"]}"'
    return q


def orcids_at(doc, i):
    """ORCIDs ADS has for the author at (0-indexed) position i."""
    fields = ("orcid_pub", "orcid_user", "orcid_other")
    return {doc[f][i] for f in fields if i < len(doc.get(f, []))} - {"-"}


def locate_author(docs):
    """Set doc["position"] (1-indexed; 0 if not found) and doc["orcid_linked"].

    With an ORCID set, papers where the author at your name's position has a
    different ORCID are someone else's, and are dropped.
    """
    a = author()
    orcid = a.get("orcid")
    last, first = a["last"].lower(), a["first"][0].lower()
    kept = []
    for doc in docs:
        names = doc.get("author", [])
        by_orcid = [
            i for i in range(len(names)) if orcid and orcid in orcids_at(doc, i)
        ]
        by_name = [
            i
            for i, n in enumerate(names)
            if n.split(",")[0].strip().lower() == last
            and n.partition(",")[2].strip().lower().startswith(first)
        ]
        if by_orcid:
            i = by_orcid[0]
        elif by_name:
            i = by_name[0]
            if orcid and orcids_at(doc, i):
                continue  # someone else with your name
        else:
            i = None
        doc["position"] = 0 if i is None else i + 1
        doc["orcid_linked"] = bool(by_orcid)
        kept.append(doc)
    return kept


# --- Fetching from ADS ------------------------------------------------------------


def get_token():
    token = os.environ.get("ADS_API_TOKEN") or os.environ.get("ADS_DEV_KEY")
    if token:
        return token.strip()
    keyfile = Path.home() / ".ads" / "dev_key"
    if keyfile.exists():
        return keyfile.read_text().strip()
    sys.exit("No ADS token: set ADS_API_TOKEN or write it to ~/.ads/dev_key")


def search(session):
    fields = [
        "bibcode", "identifier", "author", "title", "date", "year", "doctype",
        "bibstem", "pub", "property", "citation_count", "doi",
        "orcid_pub", "orcid_user", "orcid_other",
    ]  # fmt: skip
    r = session.get(
        f"{API}/search/query",
        params={
            "q": query(),
            "fl": ",".join(fields),
            "rows": 2000,
            "sort": "date desc",
        },
    )
    r.raise_for_status()
    return r.json()["response"]["docs"]


def nth_rules():
    """[[nth_author]] rules from config.toml, in order."""
    return load_config().get("nth_author", [])


def library_bibcodes(session):
    """{library name: set of bibcodes} for all your ADS libraries.

    [[nth_author]] rules sort by the libraries they name; the missing-ORCID report
    notes which papers are in any library.
    """
    r = session.get(f"{API}/biblib/libraries")
    r.raise_for_status()
    ids = {lib["name"]: lib["id"] for lib in r.json()["libraries"]}
    for rule in nth_rules():
        if rule.get("library") and rule["library"] not in ids:
            sys.exit(
                f"No ADS library named {rule['library']!r}; found: {', '.join(sorted(ids))}"
            )
    out = {}
    for name, lib_id in ids.items():
        r = session.get(f"{API}/biblib/libraries/{lib_id}", params={"rows": 2000})
        r.raise_for_status()
        out[name] = set(r.json()["documents"])
    return out


def assign_libraries(docs, libraries):
    """Set doc["libraries"]: the libraries it's in (matching any of its bibcodes)."""
    for doc in docs:
        ids = {doc["bibcode"], *doc.get("identifier", [])}
        doc["libraries"] = {
            lib for lib, bibcodes in libraries.items() if ids & bibcodes
        }


# --- Sorting into lists -----------------------------------------------------------


def overrides():
    return load_config().get("overrides", {})


def is_submitted(doc):
    """Preprint with no journal version yet (ADS merges them once published)."""
    return doc.get("doctype") == "eprint" or "arXiv" in doc.get("bibstem", [])


# Research notes (not refereed) are listed with refereed papers, marked as not refereed.
RESEARCH_NOTES = {"RNAAS"}


def is_research_note(doc):
    return bool(RESEARCH_NOTES & set(doc.get("bibstem", [])))


def ads_refereed(doc):
    """Whether a paper goes in the refereed lists: ADS's refereed flag, plus research
    notes (flagged as not refereed there); theses don't count."""
    if doc.get("doctype") == "phdthesis":
        return False
    return is_research_note(doc) or "REFEREED" in doc.get("property", [])


def nth_list(doc):
    """The first [[nth_author]] rule a paper matches (by library or title pattern)."""
    title = " ".join(doc.get("title", []))
    for rule in nth_rules():
        if rule.get("library") in doc.get("libraries", ()):
            return rule["name"]
        if rule.get("title_pattern") and re.search(rule["title_pattern"], title, re.I):
            return rule["name"]
    return UNSORTED if nth_rules() else NTH


def category(doc):
    """Which list a paper goes in (the first one it qualifies for)."""
    if doc["bibcode"] in overrides():
        return overrides()[doc["bibcode"]]
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
    if not ads_refereed(doc):
        if doc.get("doctype") == "inproceedings":
            return PROCEEDINGS
        title = " ".join(doc.get("title", []))
        if "BAAS" in bibstem or re.search(r"white\s*paper", title, re.IGNORECASE):
            return WHITEPAPERS
        return NON_REFEREED
    if doc["position"] == 1:
        return FIRST
    if doc["position"] in (2, 3):
        return SECOND_THIRD
    return nth_list(doc)


def nth_names():
    return [rule["name"] for rule in nth_rules()]


def refereed_lists():
    return {FIRST, SECOND_THIRD, NTH, UNSORTED, *nth_names()}


def not_refereed_flag(doc):
    """In a refereed list though ADS doesn't call it refereed (a research note, or a
    preprint placed there by an override)."""
    return category(doc) in refereed_lists() and "REFEREED" not in doc.get("property", [])


def not_refereed_type(doc):
    """What a flagged paper is, for the legend: "research note", "arXiv preprint", ..."""
    if is_research_note(doc):
        return "research note"
    if is_submitted(doc):
        return "arXiv preprint"
    return doc.get("doctype", "paper")


def not_refereed_marker():
    """[classify] not_refereed_marker, added to the year of flagged entries."""
    return load_config().get("classify", {}).get("not_refereed_marker", r"$^\dagger$")


def lists_of(doc):
    """Every list a paper appears in: its own, plus 3_nth_author for its sub-lists."""
    cat = category(doc)
    if cat in {UNSORTED, *nth_names()}:
        return [cat, NTH]
    return [cat]


def categorize(docs):
    names = [
        UNSORTED, NON_REFEREED, FIRST, SECOND_THIRD, NTH, *nth_names(),
        PROCEEDINGS, WHITEPAPERS, *OTHER,
    ]  # fmt: skip
    groups = {name: [] for name in names}
    for doc in docs:
        for name in lists_of(doc):
            groups.setdefault(name, []).append(doc["bibcode"])
    return groups


def save_records(docs):
    """Write the paper metadata to papers.json, for pub_stats.py and prepare_cv.py."""
    records = [
        {
            "bibcode": d["bibcode"],
            "year": d.get("year"),
            "doctype": d.get("doctype"),
            "title": " ".join(d.get("title", [])),
            "author_position": d["position"],
            "n_authors": len(d.get("author", [])),
            "citations": d.get("citation_count", 0),
            "refereed": category(d) in refereed_lists() and not not_refereed_flag(d),
            "not_refereed_flag": not_refereed_flag(d),
            "not_refereed_type": not_refereed_type(d) if not_refereed_flag(d) else None,
            "submitted": is_submitted(d),
            "orcid_linked": d["orcid_linked"],
            "category": category(d),
            "lists": lists_of(d),
        }
        for d in docs
    ]
    path = OUTDIR / "papers.json"
    path.write_text(json.dumps(records, indent=2) + "\n")
    print(f"{len(records):4d}  {path.relative_to(OUTDIR.parent)}")


def report_missing_orcid(docs):
    """List papers where ADS doesn't link your ORCID, by list, and warn about refereed ones.

    Papers that are in one of your ADS libraries are tagged as such.
    """
    if not author().get("orcid"):
        return
    nth = [*nth_names(), UNSORTED] if nth_rules() else [NTH]
    types = {
        "Refereed": [FIRST, SECOND_THIRD, *nth],
        "Non-refereed": [NON_REFEREED, PROCEEDINGS, WHITEPAPERS],
        "Other": OTHER,
    }

    def link(d):
        tag = " (in your ADS library)" if d.get("libraries") else ""
        return f"- [{' '.join(d.get('title', []))}]({ads_url(d)}){tag}"

    path = OUTDIR / "missing_orcid.md"
    lines = [
        "# Papers missing your ORCID",
        "",
        (
            f"Papers where the ADS entry is not linked to ORCID {author()['orcid']}. "
            "Claim them in [ADS](https://ui.adsabs.harvard.edu/user/orcid) to fix."
        ),
    ]
    for kind, names in types.items():
        group = [d for d in docs if category(d) in names]
        missing = [d for d in group if not d["orcid_linked"]]
        lines += ["", f"## {kind}: {len(missing)} of {len(group)} missing"]
        for name in names:
            in_list = [d for d in group if category(d) == name]
            listed = [d for d in in_list if not d["orcid_linked"]]
            lines += ["", f"### {name}: {len(listed)} of {len(in_list)} missing"]
            lines += [link(d) for d in listed]
        if kind == "Refereed" and missing:
            print(
                f"\nWarning: {len(missing)} of {len(group)} refereed papers have no ORCID "
                f"linked to your name in ADS; see {path.relative_to(OUTDIR.parent)}"
            )
    path.write_text("\n".join(lines) + "\n")


# --- Formatting -------------------------------------------------------------------


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
    if not_refereed_flag(doc):  # e.g. \cvitem{2024$^\dagger$}
        entry = re.sub(
            r"\\cvitem\{(\d{4})\}",
            lambda m: rf"\cvitem{{{m.group(1)}{not_refereed_marker()}}}",
            entry,
            count=1,
        )
    if abbreviations:
        entry = abbreviate(entry, doc, abbreviations)
    # Drop dangling commas left by empty fields (e.g. a thesis has no volume or page).
    entry = re.sub(r"(,\s*)+}\s*$", "}", entry)
    for char, tex_char in UNICODE_FIXES.items():
        entry = entry.replace(char, tex_char)
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
    if doc["bibcode"] in overrides():
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
    """Bold your name, or flag that you're hidden in the 'et al.'."""
    entry, n = name_pattern().subn(lambda m: rf"\textbf{{{m.group(0)}}}", entry)
    if n:
        return entry
    # Insert right after the author list (i.e., before the quoted title).
    idx = entry.find(", ``")
    if idx < 0:
        return entry.rstrip().rstrip("}") + incl_marker() + "}"
    return entry[:idx] + incl_marker() + entry[idx:]


def write(name, entries):
    path = OUTDIR / f"{name}.tex"
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n".join(highlight(e) for e in entries) + "\n")
    print(f"{len(entries):4d}  {path.relative_to(OUTDIR.parent)}")


def max_authors_per_list(names, override=None):
    """{list name: authors to show}, from config.toml unless overridden."""
    limits = load_config().get("max_authors", {})
    default = limits.get("default", MAX_AUTHORS)
    return {name: override or limits.get(name, default) for name in names}


def max_authors_per_section(list_limits, override=None):
    """{(CV section, list name): authors to show} for the cv/publists/ sections.

    Uses [cv_max_authors] in config.toml, falling back to each list's own limit.
    """
    limits = load_config().get("cv_max_authors", {})
    out = {}
    for section, names in prepare_cv.sections().items():
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
    parser.add_argument("--pdf", action="store_true", help="also compile cv/publication_list.pdf")
    args = parser.parse_args()

    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {get_token()}"

    docs = locate_author(search(session))
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
        needed.setdefault(n, set()).update(groups.get(name, []))
    formatted = {
        n: format_all(session, [d for d in docs if d["bibcode"] in bibcodes], n)
        for n, bibcodes in needed.items()
    }
    for name, bibcodes in groups.items():
        write(name, [formatted[limits[name]][b] for b in bibcodes])

    # Entries for the CV sections, for prepare_cv.py.
    cv_entries = {}
    for (section, name), n in cv_limits.items():
        for b in groups.get(name, []):
            cv_entries.setdefault(section, {})[b] = highlight(formatted[n][b])
    (OUTDIR / "cv_entries.json").write_text(json.dumps(cv_entries, indent=2) + "\n")

    def print_links(bibcodes):
        for b in bibcodes:
            doc = by_bibcode[b]
            print(f"  {ads_url(doc)}  {' '.join(doc.get('title', []))[:70]}")

    if groups[UNSORTED]:
        libraries = " / ".join(r["library"] for r in nth_rules() if r.get("library"))
        print(f"\nUnsorted papers: add to an ADS library ({libraries}) and rerun:")
        print_links(groups[UNSORTED])

    report_missing_orcid(docs)

    print("\nCV sections:")
    prepare_cv.main(pdf=args.pdf)

    if groups[NON_REFEREED]:
        stars = "*" * 80
        print(
            f"\n{stars}\nNon-refereed (possibly submitted): move by hand if submitted:"
        )
        print_links(groups[NON_REFEREED])
        print(stars)


if __name__ == "__main__":
    main()
