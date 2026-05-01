// Render selected + full publications from data/publications.json
// and data/publications-config.json.
//
// Config controls which papers appear in Selected (by DOI) and which
// papers get extra "pub-links" (project page, code, slides, preprint, video).

(function () {
  const selectedRoot = document.getElementById("pubs-selected");
  const allRoot = document.getElementById("pubs-all");
  const metaEl = document.getElementById("pubs-meta");
  if (!allRoot) return;

  Promise.all([
    fetch("data/publications.json", { cache: "no-cache" }).then((r) => r.json()),
    fetch("data/publications-config.json", { cache: "no-cache" }).then((r) => r.json()),
  ])
    .then(([pubs, cfg]) => render(pubs, cfg))
    .catch((err) => {
      console.error(err);
      if (selectedRoot) selectedRoot.innerHTML = "";
      allRoot.innerHTML =
        '<p class="pubs-error">Could not load publications data. Please try again later.</p>';
    });

  function normalizeDoi(d) {
    return (d || "").replace(/^https?:\/\/doi\.org\//i, "").toLowerCase();
  }

  function normalizeTitle(t) {
    return (t || "").toLowerCase().replace(/\s+/g, " ").trim();
  }

  function escape(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatAuthors(authors) {
    if (!authors || !authors.length) return "";
    const parts = authors.map((a) => {
      const isMe = /\bfranke,?\s*k\b|\bkatrin\s+franke\b/i.test(a);
      const safe = escape(a);
      return isMe ? `<span class="me">${safe}</span>` : safe;
    });
    return parts.join(", ");
  }

  function renderLinks(paper, override) {
    const links = [];
    const url = paper.url || (paper.doi ? `https://doi.org/${paper.doi}` : null);
    if (url) links.push({ label: "Paper", href: url });
    if (override) {
      if (override.preprint) links.push({ label: "Preprint", href: override.preprint });
      if (override.project_page) links.push({ label: "Project page", href: override.project_page });
      if (override.code) links.push({ label: "Code", href: override.code });
      if (override.data) links.push({ label: "Data", href: override.data });
      if (override.slides) links.push({ label: "Slides", href: override.slides });
      if (override.video) links.push({ label: "Video", href: override.video });
    }
    if (!links.length) return "";
    return (
      '<div class="pub-links">' +
      links
        .map(
          (l) =>
            `<a href="${escape(l.href)}" target="_blank" rel="noopener">${escape(l.label)}</a>`
        )
        .join("") +
      "</div>"
    );
  }

  function renderPub(paper, override) {
    const authors = formatAuthors(paper.authors);
    const title = escape(paper.title || "");
    const venue = paper.venue ? `<em>${escape(paper.venue)}</em>` : "";
    const year = paper.year ? ` (${paper.year})` : "";
    const venueLine = venue || year ? `<div class="venue">${venue}${year}</div>` : "";
    return (
      '<div class="pub">' +
      (authors ? `<div class="authors">${authors}</div>` : "") +
      `<div class="title">${title}</div>` +
      venueLine +
      renderLinks(paper, override) +
      "</div>"
    );
  }

  function normalizeExtra(e) {
    const doi = (e.doi || "").replace(/^https?:\/\/doi\.org\//i, "") || null;
    return {
      id: null,
      doi: doi,
      title: e.title,
      year: e.year || null,
      date: e.date || (e.year ? `${e.year}-12-31` : null),
      authors: e.authors || [],
      venue: e.venue || null,
      url: e.url || (doi ? `https://doi.org/${doi}` : null),
      type: e.type || "article",
      manual: true,
    };
  }

  function render(pubs, cfg) {
    const openalexWorks = (pubs && pubs.works) || [];
    const overrides = (cfg && cfg.overrides) || {};
    const selected = (cfg && cfg.selected) || [];
    const excludeDois = new Set(
      ((cfg && cfg.exclude_dois) || []).map(normalizeDoi).filter(Boolean)
    );
    const extras = ((cfg && cfg.extras) || [])
      .filter((e) => e && e.title)
      .map(normalizeExtra);

    // Merge extras with auto-fetched works; extras win on DOI/title collisions
    const seenDoi = new Set();
    const seenTitle = new Set();
    const works = [];
    for (const w of [...extras, ...openalexWorks]) {
      const d = normalizeDoi(w.doi);
      const t = normalizeTitle(w.title);
      if (d && seenDoi.has(d)) continue;
      if (!d && t && seenTitle.has(t)) continue;
      if (d) seenDoi.add(d);
      if (t) seenTitle.add(t);
      works.push(w);
    }
    works.sort((a, b) => {
      const da = a.date || `${a.year || 0}-00-00`;
      const db = b.date || `${b.year || 0}-00-00`;
      return db.localeCompare(da);
    });

    // Index by DOI and by openalex id for lookups
    const byDoi = new Map();
    const byId = new Map();
    for (const w of works) {
      const d = normalizeDoi(w.doi);
      if (d) byDoi.set(d, w);
      if (w.id) byId.set(w.id, w);
    }

    function lookup(entry) {
      if (entry.doi) {
        const d = normalizeDoi(entry.doi);
        if (byDoi.has(d)) return byDoi.get(d);
      }
      if (entry.openalex) {
        const id = entry.openalex.split("/").pop();
        if (byId.has(id)) return byId.get(id);
      }
      return null;
    }

    // ---------- Selected section ----------
    if (selectedRoot) {
      const items = [];
      for (const entry of selected) {
        const w = lookup(entry);
        if (!w) continue;
        const override = overrides[normalizeDoi(w.doi)] || overrides[w.id] || null;
        items.push(renderPub(w, override));
      }
      if (items.length) {
        selectedRoot.innerHTML = items.join("");
      } else {
        selectedRoot.innerHTML = "";
      }
    }

    // ---------- Full list, grouped by year ----------
    const filtered = works.filter((w) => !excludeDois.has(normalizeDoi(w.doi)));
    const byYear = new Map();
    for (const w of filtered) {
      const y = w.year || "Undated";
      if (!byYear.has(y)) byYear.set(y, []);
      byYear.get(y).push(w);
    }
    const years = [...byYear.keys()].sort((a, b) => {
      if (a === "Undated") return 1;
      if (b === "Undated") return -1;
      return b - a;
    });

    const parts = [];
    for (const y of years) {
      parts.push(`<h2 class="pub-year">${escape(String(y))}</h2>`);
      for (const w of byYear.get(y)) {
        const override = overrides[normalizeDoi(w.doi)] || overrides[w.id] || null;
        parts.push(renderPub(w, override));
      }
    }

    if (!parts.length) {
      allRoot.innerHTML =
        '<p class="pubs-loading">No publications yet. The list will populate once the weekly OpenAlex sync runs (Actions &rarr; Update publications from OpenAlex &rarr; Run workflow).</p>';
    } else {
      allRoot.innerHTML = parts.join("");
    }

    if (metaEl) {
      const sourceLabel = (pubs.source || "ORCID").toUpperCase().includes("ORCID") ? "ORCID" : pubs.source || "ORCID";
      if (pubs.generated_at) {
        const d = new Date(pubs.generated_at);
        const stamp = d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
        metaEl.textContent = `Auto-updated from ${sourceLabel} on ${stamp} · ${pubs.count ?? filtered.length} works.`;
      } else {
        metaEl.textContent = `Awaiting first ${sourceLabel} sync.`;
      }
    }
  }
})();
