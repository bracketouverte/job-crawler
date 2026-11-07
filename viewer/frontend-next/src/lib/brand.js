import { api } from "./api.js";

/** One lookup per company for the whole session; logo lookups are not worth refetching. */
const cache = new Map();

/** @param {string} company @returns {Promise<string | null>} */
export function brandDomain(company) {
  if (!cache.has(company)) {
    cache.set(
      company,
      api.get("/logo-dev/brand", { params: { company } }).then((data) => data.domain ?? null),
    );
  }
  return cache.get(company);
}
