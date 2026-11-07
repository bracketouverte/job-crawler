import { test } from "node:test";
import assert from "node:assert/strict";

import { DEFAULT_FILTERS, filtersFromSearch, filtersToSearch, toJobsParams } from "../src/lib/filters.js";

test("empty search yields defaults and no saved searches", () => {
  const { filters, searches } = filtersFromSearch("");
  assert.deepEqual(filters, DEFAULT_FILTERS);
  assert.deepEqual(searches, []);
});

test("remote defaults on and is only written when off", () => {
  assert.equal(filtersFromSearch("?remote=0").filters.remote, false);
  assert.equal(filtersFromSearch("").filters.remote, true);
  assert.equal(filtersToSearch(DEFAULT_FILTERS, []), "");
  assert.equal(filtersToSearch({ ...DEFAULT_FILTERS, remote: false }, []), "?remote=0");
});

test("filters round-trip through the query string with backend parameter names", () => {
  const filters = {
    ...DEFAULT_FILTERS,
    title: "product manager",
    myLoc: "Miami",
    company: "Acme",
    sources: ["greenhouse", "lever"],
    tiers: ["senior"],
    types: ["full_time"],
    days: "7",
    score: "4plus",
    evaluated: true,
    inc: "ai",
    exc: "sales",
    favCompanies: ["Stripe"],
    page: 3,
  };
  const query = filtersToSearch(filters, []);
  const parsed = filtersFromSearch(query);
  assert.deepEqual(parsed.filters, filters);
  assert.deepEqual(parsed.searches, []);
  assert.match(query, /sources=greenhouse%2Clever|sources=greenhouse,lever/);
});

test("page 1 is omitted from the URL", () => {
  assert.equal(filtersToSearch({ ...DEFAULT_FILTERS, page: 1 }, []), "");
  assert.equal(filtersFromSearch("?page=abc").filters.page, 1);
});

test("active saved-search ids survive as the searches param", () => {
  const query = filtersToSearch({ ...DEFAULT_FILTERS, title: "x" }, ["pm-soflo", "ai"]);
  const parsed = filtersFromSearch(query);
  assert.deepEqual(parsed.searches, ["pm-soflo", "ai"]);
  assert.equal(parsed.filters.title, "x");
});

test("toJobsParams maps filters to API params and drops empty values", () => {
  const params = JSON.parse(JSON.stringify(toJobsParams({ ...DEFAULT_FILTERS, sources: ["lever"], remote: false, page: 2 }, 50)));
  assert.deepEqual(params, {
    title: "",
    myLoc: "",
    remote: "0",
    company: "",
    sources: "lever",
    inc: "",
    exc: "",
    page: 2,
    limit: 50,
  });
});
