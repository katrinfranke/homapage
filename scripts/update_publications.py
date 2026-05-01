#!/usr/bin/env python3
"""
Build data/publications.json from ORCID + Crossref.

ORCID provides the curated, deduped list of works (one entry per work-group).
Crossref provides clean per-paper metadata (full author lists, venues, dates)
keyed by DOI. For works without a DOI, or for DOIs not in Crossref, we fall
back to ORCID's own full work record.

Run from the repo root:  python scripts/update_publications.py
No third-party deps; uses only stdlib.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "data" / "publications-config.json"
OUTPUT_PATH = ROOT / "data" / "publications.json"
UA = "kfranke.com publications updater (mailto:kafranke@stanford.edu)"
ORCID_BASE = "https://pub.orcid.org/v3.0"
CROSSREF_BASE = "https://api.crossref.org"


def fetch_json(url: str) -> dict | None:
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def extract_doi(work: dict) -> str | None:
    eids = (work.get("external-ids") or {}).get("external-id") or []
    for e in eids:
        if (e.get("external-id-type") or "").lower() == "doi":
            v = (e.get("external-id-value") or "").strip()
            if v:
                return v.replace("https://doi.org/", "").lower()
    return None


def pick_summary(group: dict) -> dict:
    """From a work-group, pick the best summary: prefer one with a DOI."""
    summaries = group.get("work-summary") or []
    for s in summaries:
        if extract_doi(s):
            return s
    return summaries[0] if summaries else {}


def parse_orcid_date(d: dict | None) -> tuple[str | None, int | None]:
    if not d:
        return None, None
    y = (d.get("year") or {}).get("value")
    if not y or not str(y).isdigit():
        return None, None
    m = (d.get("month") or {}).get("value") or "01"
    day = (d.get("day") or {}).get("value") or "01"
    iso = f"{int(y):04d}-{int(m):02d}-{int(day):02d}"
    return iso, int(y)


_TYPE_MAP = {
    "journal-article": "article",
    "preprint": "preprint",
    "posted-content": "preprint",
    "book-chapter": "book-chapter",
    "book": "book",
    "proceedings-article": "conference-paper",
    "conference-paper": "conference-paper",
    "report": "report",
    "other": "article",
}


def normalize_type(t: str | None) -> str:
    return _TYPE_MAP.get((t or "").lower(), (t or "article").lower())


def from_orcid(record: dict, put_code: int | None = None) -> dict:
    """Build a flat work entry from an ORCID summary or full record."""
    title = (((record.get("title") or {}).get("title")) or {}).get("value") or ""
    iso, yr = parse_orcid_date(record.get("publication-date"))
    venue = (record.get("journal-title") or {}).get("value")
    doi = extract_doi(record)
    url = (record.get("url") or {}).get("value") or (
        f"https://doi.org/{doi}" if doi else None
    )
    authors: list[str] = []
    for c in (record.get("contributors") or {}).get("contributor") or []:
        n = (c.get("credit-name") or {}).get("value")
        if n:
            authors.append(n)
    pc = put_code or record.get("put-code")
    return {
        "id": f"orcid:{pc}" if pc else None,
        "doi": doi,
        "title": title,
        "year": yr,
        "date": iso,
        "authors": authors,
        "venue": venue,
        "url": url,
        "type": normalize_type(record.get("type")),
    }


def from_crossref(message: dict, doi: str) -> dict:
    titles = message.get("title") or []
    title = (titles[0] if titles else "").strip()
    venues = message.get("container-title") or []
    venue = venues[0] if venues else None

    parts = None
    for k in ("published-print", "published-online", "issued", "created"):
        dp = (message.get(k) or {}).get("date-parts") or []
        if dp and dp[0]:
            parts = dp[0]
            break
    iso, yr = None, None
    if parts:
        y = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 1
        d = int(parts[2]) if len(parts) > 2 else 1
        iso = f"{y:04d}-{m:02d}-{d:02d}"
        yr = y

    authors = []
    for a in message.get("author") or []:
        given = (a.get("given") or "").strip()
        family = (a.get("family") or "").strip()
        name = (f"{given} {family}").strip() or (a.get("name") or "").strip()
        if name:
            authors.append(name)

    url = message.get("URL") or f"https://doi.org/{doi}"

    return {
        "id": f"doi:{doi}",
        "doi": doi,
        "title": title,
        "year": yr,
        "date": iso,
        "authors": authors,
        "venue": venue,
        "url": url,
        "type": normalize_type(message.get("type")),
    }


def fetch_orcid_works(orcid: str) -> list[dict]:
    data = fetch_json(f"{ORCID_BASE}/{orcid}/works")
    if not data:
        raise SystemExit(f"ORCID returned no data for {orcid}")
    return data.get("group") or []


def fetch_full_orcid_work(orcid: str, put_code: int) -> dict | None:
    return fetch_json(f"{ORCID_BASE}/{orcid}/work/{put_code}")


def fetch_crossref_work(doi: str) -> dict | None:
    url = f"{CROSSREF_BASE}/works/{urllib.parse.quote(doi, safe='/()')}"
    d = fetch_json(url)
    return (d or {}).get("message") if d else None


_TYPE_RANK = {
    "article": 0,
    "review": 0,
    "book-chapter": 1,
    "book": 1,
    "conference-paper": 2,
    "report": 3,
    "preprint": 4,
}


def _dedup_score(w: dict) -> tuple[int, int]:
    return (_TYPE_RANK.get(w.get("type"), 5), 0 if w.get("doi") else 1)


def normalize_title(t: str | None) -> str:
    return re.sub(r"\s+", " ", (t or "").lower()).strip()


def dedup_by_title(works: list[dict]) -> list[dict]:
    """Catch title-collisions ORCID's group-by-DOI didn't merge.
    Prefer published over preprint, and DOI-having over DOI-less."""
    by_key: dict[str, dict] = {}
    no_title: list[dict] = []
    for w in works:
        key = normalize_title(w.get("title"))
        if not key:
            no_title.append(w)
            continue
        if key not in by_key or _dedup_score(w) < _dedup_score(by_key[key]):
            by_key[key] = w
    return list(by_key.values()) + no_title


def main() -> int:
    cfg = json.loads(CONFIG_PATH.read_text())
    orcid = (cfg.get("orcid") or "").strip()
    if not orcid:
        raise SystemExit(
            "publications-config.json needs `orcid` filled in (e.g. 0000-0000-0000-0000)."
        )
    exclude = {
        d.lower().replace("https://doi.org/", "")
        for d in (cfg.get("exclude_dois") or [])
    }

    print(f"[orcid] fetching works for {orcid}", file=sys.stderr)
    groups = fetch_orcid_works(orcid)
    print(f"[orcid] got {len(groups)} grouped works", file=sys.stderr)

    works: list[dict] = []
    n_crossref = 0
    n_orcid_full = 0
    for g in groups:
        s = pick_summary(g)
        if not s:
            continue
        doi = extract_doi(s)
        record: dict | None = None

        if doi:
            cr = fetch_crossref_work(doi)
            time.sleep(0.1)
            if cr:
                record = from_crossref(cr, doi)
                n_crossref += 1

        if record is None:
            put_code = s.get("put-code")
            if put_code is not None:
                full = fetch_full_orcid_work(orcid, put_code)
                time.sleep(0.1)
                if full:
                    record = from_orcid(full, put_code=put_code)
                    n_orcid_full += 1

        if record is None:
            record = from_orcid(s)

        if record.get("doi") and record["doi"] in exclude:
            continue
        works.append(record)

    works = dedup_by_title(works)
    works.sort(
        key=lambda x: (x.get("date") or f"{x.get('year') or 0}-00-00"),
        reverse=True,
    )

    print(
        f"[done] {len(works)} works (crossref: {n_crossref}, orcid full: {n_orcid_full})",
        file=sys.stderr,
    )

    out = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "orcid+crossref",
        "filter": f"orcid:{orcid}",
        "count": len(works),
        "works": works,
    }
    OUTPUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"[done] wrote {OUTPUT_PATH.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
