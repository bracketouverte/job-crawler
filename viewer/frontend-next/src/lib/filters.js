/**
 * @typedef {object} Filters
 * @property {string} title
 * @property {string} myLoc
 * @property {boolean} remote
 * @property {string} days
 * @property {string} company
 * @property {string[]} sources
 * @property {string[]} tiers
 * @property {string[]} types
 * @property {"" | "none" | "4plus"} score
 * @property {boolean} evaluated
 * @property {string} inc
 * @property {string} exc
 * @property {string[]} favCompanies
 * @property {number} page
 */

/** @type {Filters} */
export const DEFAULT_FILTERS = Object.freeze({
  title: "",
  myLoc: "",
  remote: true,
  days: "",
  company: "",
  sources: [],
  tiers: [],
  types: [],
  score: "",
  evaluated: false,
  inc: "",
  exc: "",
  favCompanies: [],
  page: 1,
});

function list(params, key) {
  return params.get(key)?.split(",").filter(Boolean) ?? [];
}

/**
 * Parse the query string into filter state. Parameter names are the ones the
 * backend already accepts, so existing bookmarked URLs keep their meaning.
 * @param {string} search
 * @returns {{ filters: Filters, searches: string[] }}
 */
export function filtersFromSearch(search) {
  const params = new URLSearchParams(search);
  const filters = {
    title: params.get("title") ?? "",
    myLoc: params.get("myLoc") ?? "",
    remote: params.get("remote") !== "0",
    days: params.get("days") ?? "",
    company: params.get("company") ?? "",
    sources: list(params, "sources"),
    tiers: list(params, "tiers"),
    types: list(params, "types"),
    score: /** @type {Filters["score"]} */ (params.get("score") ?? ""),
    evaluated: params.get("evaluated") === "1",
    inc: params.get("inc") ?? "",
    exc: params.get("exc") ?? "",
    favCompanies: list(params, "favCompanies"),
    page: Number(params.get("page")) || 1,
  };
  return { filters, searches: list(params, "searches") };
}

/**
 * Serialise filter state back to a query string (leading "?" or "").
 * @param {Filters} filters
 * @param {string[]} searches active saved-search ids
 * @returns {string}
 */
export function filtersToSearch(filters, searches) {
  const params = new URLSearchParams();
  if (filters.title) params.set("title", filters.title);
  if (filters.myLoc) params.set("myLoc", filters.myLoc);
  if (!filters.remote) params.set("remote", "0");
  if (filters.days) params.set("days", filters.days);
  if (filters.company) params.set("company", filters.company);
  if (filters.sources.length) params.set("sources", filters.sources.join(","));
  if (filters.tiers.length) params.set("tiers", filters.tiers.join(","));
  if (filters.types.length) params.set("types", filters.types.join(","));
  if (filters.score) params.set("score", filters.score);
  if (filters.evaluated) params.set("evaluated", "1");
  if (filters.inc) params.set("inc", filters.inc);
  if (filters.exc) params.set("exc", filters.exc);
  if (filters.favCompanies.length) params.set("favCompanies", filters.favCompanies.join(","));
  if (filters.page > 1) params.set("page", String(filters.page));
  if (searches.length) params.set("searches", searches.join(","));
  const query = params.toString();
  return query ? `?${query}` : "";
}

/**
 * Map filter state to the `/api/jobs` query parameters.
 * @param {Filters} filters
 * @param {number} limit
 * @returns {Record<string, string | number | undefined>}
 */
export function toJobsParams(filters, limit) {
  return {
    title: filters.title,
    myLoc: filters.myLoc,
    remote: filters.remote ? undefined : "0",
    days: filters.days || undefined,
    company: filters.company,
    sources: filters.sources.join(",") || undefined,
    tiers: filters.tiers.join(",") || undefined,
    types: filters.types.join(",") || undefined,
    score: filters.score || undefined,
    evaluated: filters.evaluated ? "1" : undefined,
    inc: filters.inc,
    exc: filters.exc,
    favCompanies: filters.favCompanies.join(",") || undefined,
    page: filters.page,
    limit,
  };
}
