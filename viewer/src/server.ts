import express from "express";
import Database from "better-sqlite3";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));

const DB_PATH = process.env.CATALOG_DB ?? "/app/state/catalog.sqlite";
const LOGO_DEV_PUBLISHABLE_KEY = process.env.LOGO_DEV_PUBLISHABLE_KEY?.trim() ?? "";
const LOGO_DEV_SECRET_KEY = process.env.LOGO_DEV_SECRET_KEY?.trim() ?? "";
const PORT = parseInt(process.env.PORT ?? "3000", 10);
const LOGO_CACHE_MAX = 2000;
const logoDevBrandCache = new Map<string, string | null>();

function logoCacheSet(key: string, value: string | null): void {
  if (logoDevBrandCache.size >= LOGO_CACHE_MAX) {
    logoDevBrandCache.delete(logoDevBrandCache.keys().next().value!);
  }
  logoDevBrandCache.set(key, value);
}

type JobRow = {
  provider: string;
  source_key: string;
  job_id: string;
  title: string | null;
  location: string | null;
  employment_type: string | null;
  compensation: string | null;
  department: string | null;
  job_url: string | null;
  updated_at: string | null;
  first_seen_at: string;
  last_seen_at: string;
};

type TitleTokenGroup = {
  terms: string[];
  exclude: boolean;
};

type StatsRow = {
  provider: string;
  count: number;
};

const db = new Database(DB_PATH, { readonly: true, fileMustExist: true });

// Returns an array of token groups with exclude flags.
// Single-item group = AND bare word. Multi-item group = OR group (AND-ed with rest).
// Prefix with - to negate: "product -(owner,builder)" → include product, exclude owner/builder
// Input: "product (manager,owner) -(growth,marketing)"
function parseTitleQuery(input: string): TitleTokenGroup[] {
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

const app = express();

app.use(express.static(join(__dirname, "../public")));

app.get("/api/jobs", (req, res) => {
  const { title, location, days, company, sources, page } = req.query as Record<string, string>;

  const pageNum = Math.max(1, parseInt(page ?? "1", 10));
  const pageSize = 50;
  const offset = (pageNum - 1) * pageSize;

  const conditions: string[] = [];
  const params: unknown[] = [];

  if (title?.trim()) {
    // Parse: bare words are AND terms, (a,b,c) groups are OR terms AND-ed with rest
    // Prefix with - to exclude: "product -(growth,marketing)" → include product, exclude growth/marketing
    const tokens = parseTitleQuery(title);
    for (const token of tokens) {
      if (token.terms.length === 1) {
        if (token.exclude) {
          conditions.push("LOWER(title) NOT LIKE ?");
        } else {
          conditions.push("LOWER(title) LIKE ?");
        }
        params.push(`%${token.terms[0]}%`);
      } else {
        if (token.exclude) {
          // NOT (A OR B) = (NOT A AND NOT B)
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

  if (location?.trim()) {
    const locs = location
      .split(/[,]+/)
      .map((l) => l.trim())
      .filter(Boolean);
    const locClauses = locs.map(() => "LOWER(location) LIKE ?");
    conditions.push(`(${locClauses.join(" OR ")})`);
    for (const loc of locs) params.push(`%${loc.toLowerCase()}%`);
  }

  if (company?.trim()) {
    const companies = company
      .split(/[,]+/)
      .map((c) => c.trim())
      .filter(Boolean);
    const companyClauses = companies.map(() => "LOWER(source_key) LIKE ?");
    conditions.push(`(${companyClauses.join(" OR ")})`);
    for (const comp of companies) params.push(`%${comp.toLowerCase()}%`);
  }

  if (sources?.trim()) {
    const providerList = sources
      .split(/[,]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (providerList.length > 0) {
      const providerClauses = providerList.map(() => "provider = ?");
      conditions.push(`(${providerClauses.join(" OR ")})`);
      for (const provider of providerList) params.push(provider);
    }
  }

  if (days?.trim()) {
    const n = parseInt(days, 10);
    if (!isNaN(n) && n > 0) {
      conditions.push("last_seen_at >= datetime('now', ?)");
      params.push(`-${n} days`);
    }
  }

  const where = conditions.length > 0 ? `WHERE ${conditions.join(" AND ")}` : "";

  try {
    const total = (
      db.prepare(`SELECT COUNT(*) as n FROM catalog_jobs ${where}`).get(...params) as {
        n: number;
      }
    ).n;

    const jobs = db
      .prepare(
        `SELECT provider, source_key, job_id, title, location, employment_type,
                compensation, department, job_url, updated_at, first_seen_at, last_seen_at
         FROM catalog_jobs ${where}
         ORDER BY first_seen_at DESC
         LIMIT ? OFFSET ?`
      )
      .all(...params, pageSize, offset) as JobRow[];

    res.json({ total, page: pageNum, pageSize, jobs });
  } catch (err) {
    console.error("/api/jobs error:", err);
    res.status(500).json({ error: String(err) });
  }
});

app.get("/api/sources", (_req, res) => {
  try {
    const providers = db
      .prepare(`SELECT DISTINCT provider FROM catalog_jobs ORDER BY provider`)
      .all() as { provider: string }[];

    res.json({ sources: providers.map((p) => p.provider) });
  } catch (err) {
    console.error("/api/sources error:", err);
    res.status(500).json({ error: String(err) });
  }
});

app.get("/api/stats", (_req, res) => {
  try {
    const byProvider = db
      .prepare(
        `SELECT provider, COUNT(*) as count FROM catalog_jobs GROUP BY provider ORDER BY count DESC`
      )
      .all() as StatsRow[];

    const total = byProvider.reduce((s, r) => s + r.count, 0);

    const lastSeen = (
      db.prepare(`SELECT MAX(last_seen_at) as ts FROM catalog_jobs`).get() as {
        ts: string | null;
      }
    ).ts;

    res.json({ total, byProvider, lastCrawl: lastSeen });
  } catch (err) {
    console.error("/api/stats error:", err);
    res.status(500).json({ error: String(err) });
  }
});

app.get("/api/config", (_req, res) => {
  res.json({
    logoDevPublishableKey: LOGO_DEV_PUBLISHABLE_KEY || null,
    hasLogoDevBrandSearch: Boolean(LOGO_DEV_SECRET_KEY),
  });
});

app.get("/api/logo-dev/brand", async (req, res) => {
  if (!LOGO_DEV_SECRET_KEY) {
    res.json({ domain: null });
    return;
  }

  const company = String(req.query.company ?? "").trim();
  if (!company) {
    res.status(400).json({ error: "company is required" });
    return;
  }

  const cacheKey = company.toLowerCase();
  if (logoDevBrandCache.has(cacheKey)) {
    res.json({ domain: logoDevBrandCache.get(cacheKey) ?? null });
    return;
  }

  try {
    const url = new URL("https://api.logo.dev/search");
    url.searchParams.set("q", company);
    url.searchParams.set("strategy", "match");

    const response = await fetch(url, {
      headers: {
        Authorization: `Bearer ${LOGO_DEV_SECRET_KEY}`,
      },
    });

    if (!response.ok) {
      throw new Error(`Logo.dev search failed with status ${response.status}`);
    }

    const data = (await response.json()) as Array<{ domain?: string }>;
    const domain = String(data?.[0]?.domain ?? "").trim() || null;
    logoCacheSet(cacheKey, domain);
    res.json({ domain });
  } catch (err) {
    console.error("/api/logo-dev/brand error:", err);
    res.status(502).json({ error: "Logo.dev brand search failed" });
  }
});

app.listen(PORT, () => {
  console.log(`viewer listening on http://localhost:${PORT}`);
});
