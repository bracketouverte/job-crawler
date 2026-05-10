import type { TitleTokenGroup } from "./types.js";

// Returns an array of token groups with exclude flags.
// Single-item group = AND bare word. Multi-item group = OR group (AND-ed with rest).
// Prefix with - to negate: "product -(owner,builder)" → include product, exclude owner/builder
// Input: "product (manager,owner) -(growth,marketing)"
export function parseTitleQuery(input: string): TitleTokenGroup[] {
  const tokens: TitleTokenGroup[] = [];
  const str = input.trim();
  let i = 0;
  while (i < str.length) {
    const isNegated = str[i] === "-";
    if (isNegated) i++;

    if (str[i] === "(") {
      const end = str.indexOf(")", i);
      const inner = end === -1 ? str.slice(i + 1) : str.slice(i + 1, end);
      const terms = inner.split(",").map((t) => t.trim().toLowerCase()).filter(Boolean);
      if (terms.length > 0) tokens.push({ terms, exclude: isNegated });
      i = end === -1 ? str.length : end + 1;
    } else {
      const match = str.slice(i).match(/^[^\s(]+/);
      if (match) {
        const word = match[0].toLowerCase();
        if (word) tokens.push({ terms: [word], exclude: isNegated });
        i += match[0].length;
      } else {
        i++;
      }
    }
  }
  return tokens;
}

// Escape a term for FTS5 query syntax (wrap in double quotes to treat as a phrase).
function ftsEscape(term: string): string {
  return `"${term.replace(/"/g, '""')}"`;
}

// Returns true when all token groups are simple single-term non-negated ANDs —
// the easy case that maps directly to FTS5 AND queries.
function isSimpleFtsQuery(tokens: TitleTokenGroup[]): boolean {
  return tokens.length > 0 && tokens.every((t) => t.terms.length === 1 && !t.exclude);
}

export function addJobFilterConditions(
  filters: {
    title?: string | number | null;
    location?: string | number | null;
    company?: string | number | null;
    sources?: string | string[] | null;
    days?: string | number | null;
    favCompanies?: string[] | null;
  },
): { conditions: string[]; params: unknown[] } {
  const conditions: string[] = [];
  const params: unknown[] = [];
  const title = String(filters.title ?? "");
  const location = String(filters.location ?? "");
  const company = String(filters.company ?? "");
  const days = String(filters.days ?? "");
  const sources = Array.isArray(filters.sources) ? filters.sources.join(",") : String(filters.sources ?? "");

  if (title.trim()) {
    const tokens = parseTitleQuery(title);

    if (isSimpleFtsQuery(tokens)) {
      // FTS5 path: all plain AND terms — emit a single rowid IN (SELECT rowid FROM fts WHERE title MATCH ?)
      const ftsQuery = tokens.map((t) => ftsEscape(t.terms[0]!)).join(" ");
      conditions.push(
        `rowid IN (SELECT rowid FROM catalog_jobs_fts WHERE catalog_jobs_fts MATCH ?)`,
      );
      params.push(`title:${ftsQuery}`);
    } else {
      // Fallback: complex query (negation / OR groups) — use LIKE as before
      for (const token of tokens) {
        if (token.terms.length === 1) {
          conditions.push(token.exclude ? "LOWER(title) NOT LIKE ?" : "LOWER(title) LIKE ?");
          params.push(`%${token.terms[0]}%`);
        } else {
          if (token.exclude) {
            const notClauses = token.terms.map(() => "LOWER(title) NOT LIKE ?");
            conditions.push(`(${notClauses.join(" AND ")})`);
            for (const t of token.terms) params.push(`%${t}%`);
          } else {
            const orClauses = token.terms.map(() => "LOWER(title) LIKE ?");
            conditions.push(`(${orClauses.join(" OR ")})`);
            for (const t of token.terms) params.push(`%${t}%`);
          }
        }
      }
    }
  }

  if (location.trim()) {
    const locs = location.split(/[,]+/).map((l) => l.trim()).filter(Boolean);
    if (locs.length === 1) {
      // Single location term: use FTS5 on the location column
      conditions.push(
        `rowid IN (SELECT rowid FROM catalog_jobs_fts WHERE catalog_jobs_fts MATCH ?)`,
      );
      params.push(`location:${ftsEscape(locs[0]!)}`);
    } else {
      // Multiple location terms: fall back to LIKE OR
      const locClauses = locs.map(() => "LOWER(location) LIKE ?");
      conditions.push(`(${locClauses.join(" OR ")})`);
      for (const loc of locs) params.push(`%${loc.toLowerCase()}%`);
    }
  }

  if (company.trim()) {
    const companies = company.split(/[,]+/).map((c) => c.trim()).filter(Boolean);
    const companyClauses = companies.map(() => "LOWER(source_key) LIKE ?");
    conditions.push(`(${companyClauses.join(" OR ")})`);
    for (const comp of companies) params.push(`%${comp.toLowerCase()}%`);
  }

  if (sources.trim()) {
    const providerList = sources.split(/[,]+/).map((s) => s.trim()).filter(Boolean);
    if (providerList.length > 0) {
      const providerClauses = providerList.map(() => "provider = ?");
      conditions.push(`(${providerClauses.join(" OR ")})`);
      for (const provider of providerList) params.push(provider);
    }
  }

  if (days.trim()) {
    const n = parseInt(days, 10);
    if (!Number.isNaN(n) && n > 0) {
      conditions.push("COALESCE(posted_at, first_seen_at) >= datetime('now', ?)");
      params.push(`-${n} days`);
    }
  }

  if (filters.favCompanies && filters.favCompanies.length > 0) {
    const favClauses = filters.favCompanies.map(() => "LOWER(source_key) = ?");
    conditions.push(`(${favClauses.join(" OR ")})`);
    for (const fc of filters.favCompanies) params.push(fc.toLowerCase());
  }

  // evaluatedKeys filtering is handled via the analysis_score column in server.ts

  return { conditions, params };
}
