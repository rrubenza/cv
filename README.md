# cv

Keeps the publication lists in my CV up to date from NASA ADS, with my name in bold.

See a compiled example at [cv/publication_list.pdf](cv/publication_list.pdf).

New: now configurable for any user! See the greatly expanded `config.toml`.

## Usage

Requires an [ADS API token](https://ui.adsabs.harvard.edu/user/settings/token), saved in `~/.ads/dev_key` or exported as `ADS_API_TOKEN`.

All settings live in `config.toml`, including formatting rules (see the [ADS export help](https://ui.adsabs.harvard.edu/help/actions/export)).

Everything in `pubs/` is auto-generated and safe to delete before a re-run.

```bash
uv run scripts/update_pubs.py            # refresh the lists from ADS
uv run scripts/update_pubs.py --maxauthors 5   # same, 5 authors everywhere (lists and CV)
uv run scripts/pub_stats.py              # summary stats from the last update
uv run scripts/prepare_cv.py             # just refresh cv/publists/ from the lists
uv run scripts/update_pubs.py --pdf      # also compile cv/publication_list.pdf
uv run scripts/prepare_cv.py --pdf-only  # just recompile the PDF (e.g. after editing the preamble)
```

This writes LaTeX `\cvitem` lists (for use with [`\documentclass{moderncv}`](https://github.com/moderncv)) to `pubs/`, sorted in reverse chronological order. Note `prepare_cv.py`, which merges lists into the CV section files in `cv/publists/` set by `[cv_sections]` (keeping each file's hand-written header), runs automatically at the end of `update_pubs.py`, but you can also run it itself to just update that step.


| File | Contents |
| --- | --- |
| `all.tex` | every paper, full author list |
| `00_unsorted.tex` | 4th+ author refereed papers not matching a `[[nth_author]]` ADS library |
| `0_non_refereed.tex` | everything else not refereed, mostly preprints |
| `1_first_author.tex` | 1st-author refereed papers |
| `2_second_third_author.tex` | 2nd- and 3rd-author refereed papers |
| `3_nth_author.tex` | all 4th+ author refereed papers |
| `3.x_*.tex` | your `[[nth_author]]` sub-lists of those (e.g. `3.1_as_collaborator`) |
| `4_proceedings.tex` | conference proceedings |
| `5_whitepapers.tex` | white papers (e.g. Astro2020 in BAAS) |
| `other/thesis.tex` | PhD thesis |
| `other/zenodo.tex` | Zenodo records |
| `other/vizier.tex` | VizieR data catalogs |
| `other/code.tex` | other software (e.g. ASCL entries) |
| `other/abstracts.tex` | meeting abstracts |
| `papers.json` | per-paper metadata (author position, citations, ...) |
| `missing_orcid.md` | papers where ADS doesn't link your ORCID to your name |

See `cv/` for an example CV usage; just the publication list is compiled 
and displayed for reference at `cv/publication_list.pdf`.

## Setting it up for your own publications

In `config.toml`:

1. **`[author]`**: your `first`, `middle` (optional) and `last` name. Used to resolve the desired name formatting (e.g., "R.~A. Rubenzahl", "Rubenzahl, R. A.", ...) and bolding. Add your `orcid` to catch papers under other name variants and skip papers by homonymous others; papers where ADS doesn't link your ORCID are listed in `pubs/missing_orcid.md`, claim these in ADS to resolve.
2. **`[[nth_author]]`**: optional sub-lists for papers where you're 4th author or later. Make an ADS library for each (e.g. "as observer"), add papers to it, and name it here; a rule can instead match titles with a regex (`title_pattern`), see the "TESS-Keck Survey" example I use. Entries which are not able to be sorted (i.e. they do not appear in your ADS libraries) are flagged and printed so you can file them appropriately (and then re-run). Without rules, all go in `3_nth_author.tex`.
3. **`[overrides]`**: hard rules to place individual specific papers (by ADS bibcode) in a named list. Useful for e.g. preprints that should go in a named sub-list.
4. **`[cv_sections]`**: names the lists to populate `cv/publists/` files, which are to be copied/transfered into the CV. Missing files are created with a minimal `\subsection` header for display in your CV; edit this directly in the `for_cv/list.tex` with what you want, it will persist over re-runs (only entries from the first dated `\cvitem` and below are overwritten).
5. **`[max_authors]`, `[cv_max_authors]`, `[format]`**: author counts and the ADS export formats.
