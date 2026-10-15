# cv

Keeps the publication lists in my CV up to date from NASA ADS, with my name in bold.

## Usage

Requires an [ADS API token](https://ui.adsabs.harvard.edu/user/settings/token),
saved in `~/.ads/dev_key` or exported as `ADS_API_TOKEN`.

Define formattng rules and other settings in `config.toml` (see the [ADS export help](https://ui.adsabs.harvard.edu/help/actions/export)).

```bash
uv run scripts/update_pubs.py            # refresh the lists from ADS
uv run scripts/update_pubs.py --maxauthors 5   # same, 5 authors everywhere (lists and CV)
uv run scripts/pub_stats.py              # summary stats from the last update
uv run scripts/prepare_cv.py             # just refresh pubs/for_cv/ from the lists
```

This writes LaTeX `\cvitem` lists (for use with `\documentclass{moderncv}`) to `pubs/`, newest first:

| File | Contents |
| --- | --- |
| `all.tex` | every paper, full author list |
| `00_unsorted.tex` | other 4th+ author refereed papers: add these to one of the libraries |
| `0_non_refereed.tex` | everything else not refereed, mostly preprints |
| `1_first_author.tex` | 1st-author refereed papers |
| `2_second_third_author.tex` | 2nd- and 3rd-author refereed papers |
| `3_as_collaborator.tex` | 4th+ author refereed papers in my "as collaborator" ADS library |
| `4_as_observer.tex` | 4th+ author refereed papers in my "as observer" ADS library |
| `5_tks.tex` | TESS-Keck Survey refereed papers (4th+ author) |
| `6_proceedings.tex` | conference proceedings |
| `7_whitepapers.tex` | white papers (e.g. Astro2020 in BAAS) |
| `other/thesis.tex` | my PhD thesis |
| `other/zenodo.tex` | Zenodo records |
| `other/vizier.tex` | VizieR data catalogs |
| `other/code.tex` | other software (e.g. ASCL entries) |
| `other/abstracts.tex` | meeting abstracts |
| `papers.json` | per-paper metadata (author position, citations, ...) |

