#!/usr/bin/env python3
"""
Fetch all works for a given author from OpenAlex and write data/publications.json.

Config (data/publications-config.json) provides either:
  - orcid: "0000-0003-XXXX-XXXX"  (preferred)
  - openalex_author_id: "A1234567890"

Run from the repo root:  python scripts/update_publications.py
No third-party deps; uses only stdlib.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "data" / "publications-config.json"
OUTPUT_PATH = ROOT / "data" / "publications.json"
UA = "kfranke.com publications updater (mailto:kafranke@stanford.edu)"
BASE = "https://api.openalex.org"
SELECT_FIELDS = ",".join([
    "id",
    "doi",
    "title",
    "display_name",
    "publication_year",
    "publication_date",
    "authorships",
    "primary_location",
    "type",
    "type_crossref",
    "is_paratext",
    "is_retracted",
])


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def get_filter_for_config(cfg: dict) -> str:
    orcid = (cfg.get("orcid") or "").strip()
    oaid = (cfg.get("openalex_author_id") or "").strip()
    if orcid:
        # OpenAlex accepts bare ORCIDs or full URLs in this filter
        return f"authorships.author.orcid:{orcid}"
    if oaid:
        if not oaid.upper().startswith("A"):
            raise SystemExit(f"openalex_author_id should look like A1234567890 (got {oaid!r})")
        return f"authorships.author.id:{oaid}"
    raise SystemExit(
        "publications-config.json needs either `orcid` or `openalex_author_id` filled in."
    )


def fetch_all_works(author_filter: str) -> list[dict]:
    works: list[dict] = []
    cursor = "*"
    while cursor:
        qs = urllib.parse.urlencode({
            "filter": author_filter,
            "per-page": "200",
            "cursor": cursor,
            "select": SELECT_FIELDS,
            "mailto": "kafranke@stanford.edu",
        })
        data = fetch_json(f"{BASE}/works?{qs}")
        works.extend(data.get("results") or [])
        cursor = (data.get("meta") or {}).get("next_cursor")
        time.sleep(0.15)  # polite pacing
    return works


def clean_work(w: dict) -> dict:
    primary = w.get("primary_location") or {}
    source = primary.get("source") or {}
    doi = (w.get("doi") or "").replace("https://doi.org/", "") or None
    authors = []
    for a in w.get("authorships") or []:
        name = ((a or {}).get("author") or {}).get("display_name")
        if name:
            authors.append(name)
    return {
        "id": (w.get("id") or "").split("/")[-1] or None,
        "doi": doi,
        "title": w.get("title") or w.get("display_name"),
        "year": w.get("publication_year"),
        "date": w.get("publication_date"),
        "authors": authors,
        "venue": source.get("display_name"),
        "url": primary.get("landing_page_url") or (f"https://doi.org/{doi}" if doi else None),
        "type": w.get("type"),
    }


def main() -> int:
    cfg = json.loads(CONFIG_PATH.read_text())
    author_filter = get_filter_for_config(cfg)
    exclude = {d.lower() for d in (cfg.get("exclude_dois") or [])}

    print(f"[openalex] fetching works with filter: {author_filter}", file=sys.stderr)
    raw = fetch_all_works(author_filter)
    print(f"[openalex] got {len(raw)} raw works", file=sys.stderr)

    works = []
    seen_doi = set()
    for w in raw:
        if w.get("is_paratext") or w.get("is_retracted"):
            continue
        c = clean_work(w)
        doi = (c.get("doi") or "").lower()
        if doi and doi in exclude:
            continue
        if doi:
            if doi in seen_doi:
                continue
            seen_doi.add(doi)
        works.append(c)

    works.sort(key=lambda x: (x.get("date") or f"{x.get('year') or 0}-00-00"), reverse=True)
    # Note: extras, selected, overrides and exclude_dois from the config are
    # applied client-side by assets/js/publications.js at render time, so
    # changes to the config take effect immediately without re-running the
    # workflow. This script only mirrors what OpenAlex knows.

    out = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "openalex",
        "filter": author_filter,
        "count": len(works),
        "works": works,
    }
    OUTPUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"[openalex] wrote {len(works)} cleaned works to {OUTPUT_PATH.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
