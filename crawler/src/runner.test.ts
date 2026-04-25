import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { runCrawler } from "./runner.js";

test("runCrawler writes JSONL and report while isolating failures", async () => {
  const dir = await mkdtemp(join(tmpdir(), "crawler-test-"));
  const sources = join(dir, "sources");
  await mkdir(sources);
  await writeFile(join(sources, "lever.json"), JSON.stringify({
    provider: "lever",
    companies: [{ identifier: "ok" }, { identifier: "missing" }]
  }));

  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input) => {
    const url = String(input);
    if (url.includes("/ok?")) {
      return new Response(JSON.stringify([
        { id: "1", text: "Engineer", hostedUrl: "https://jobs.lever.co/ok/1" }
      ]), { status: 200 });
    }
    return new Response("not found", { status: 404 });
  };

  try {
    const out = join(dir, "out", "jobs.jsonl");
    const reportPath = join(dir, "out", "report.json");
    const report = await runCrawler({
      sourcesDir: sources,
      selectedProviders: ["lever"],
      concurrency: 2,
      outFile: out,
      reportFile: reportPath,
      progressEveryMs: 0,
      providerConcurrency: {},
      timeoutMs: 1000,
      retries: 0
    });

    const jsonl = await readFile(out, "utf8");
    assert.match(jsonl, /Engineer/);
    assert.equal(report.providers.lever.succeeded, 1);
    assert.equal(report.providers.lever.failed, 1);
    assert.equal(report.total_jobs, 1);
  } finally {
    globalThis.fetch = originalFetch;
    await rm(dir, { recursive: true, force: true });
  }
});

test("runCrawler skips sources from an exclusion JSONL file", async () => {
  const dir = await mkdtemp(join(tmpdir(), "crawler-test-"));
  const sources = join(dir, "sources");
  await mkdir(sources);
  await writeFile(join(sources, "lever.json"), JSON.stringify({
    provider: "lever",
    companies: [{ identifier: "ok" }, { identifier: "missing" }]
  }));
  const excludeSourcesFile = join(dir, "exclude.jsonl");
  await writeFile(excludeSourcesFile, `${JSON.stringify({
    provider: "lever",
    source_key: "missing",
    reason: "http_404"
  })}\n`);

  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input) => {
    const url = String(input);
    if (url.includes("/missing?")) {
      throw new Error("excluded source was fetched");
    }
    return new Response(JSON.stringify([
      { id: "1", text: "Engineer", hostedUrl: "https://jobs.lever.co/ok/1" }
    ]), { status: 200 });
  };

  try {
    const report = await runCrawler({
      sourcesDir: sources,
      selectedProviders: ["lever"],
      concurrency: 2,
      outFile: join(dir, "out", "jobs.jsonl"),
      reportFile: join(dir, "out", "report.json"),
      excludeSourcesFile,
      progressEveryMs: 0,
      providerConcurrency: {},
      timeoutMs: 1000,
      retries: 0
    });

    assert.equal(report.providers.lever.sources, 2);
    assert.equal(report.providers.lever.skipped, 1);
    assert.equal(report.skipped_sources, 1);
    assert.equal(report.skipped_by_provider.lever, 1);
    assert.equal(report.providers.lever.succeeded, 1);
    assert.equal(report.providers.lever.failed, 0);
  } finally {
    globalThis.fetch = originalFetch;
    await rm(dir, { recursive: true, force: true });
  }
});

test("runCrawler filters jobs by updated_at age when maxAgeHours is set", async () => {
  const dir = await mkdtemp(join(tmpdir(), "crawler-test-"));
  const sources = join(dir, "sources");
  await mkdir(sources);
  await writeFile(join(sources, "greenhouse.json"), JSON.stringify({
    provider: "greenhouse",
    companies: [{ identifier: "acme" }]
  }));

  const recent = new Date(Date.now() - (2 * 60 * 60 * 1000)).toISOString();
  const stale = new Date(Date.now() - (48 * 60 * 60 * 1000)).toISOString();

  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input) => {
    const url = String(input);
    if (!url.includes("boards-api.greenhouse.io")) {
      throw new Error(`unexpected url: ${url}`);
    }
    return new Response(JSON.stringify({
      jobs: [
        { id: "recent", title: "Recent Job", updated_at: recent, absolute_url: "https://example.com/recent" },
        { id: "stale", title: "Stale Job", updated_at: stale, absolute_url: "https://example.com/stale" },
        { id: "missing", title: "Missing Date", absolute_url: "https://example.com/missing" }
      ]
    }), { status: 200 });
  };

  try {
    const out = join(dir, "out", "jobs.jsonl");
    const reportPath = join(dir, "out", "report.json");
    const report = await runCrawler({
      sourcesDir: sources,
      selectedProviders: ["greenhouse"],
      concurrency: 1,
      outFile: out,
      reportFile: reportPath,
      maxAgeHours: 24,
      progressEveryMs: 0,
      providerConcurrency: {},
      timeoutMs: 1000,
      retries: 0
    });

    const jsonl = await readFile(out, "utf8");
    assert.match(jsonl, /Recent Job/);
    assert.doesNotMatch(jsonl, /Stale Job/);
    assert.doesNotMatch(jsonl, /Missing Date/);
    assert.equal(report.total_jobs, 1);
    assert.equal(report.providers.greenhouse.succeeded, 1);
    assert.equal(report.providers.greenhouse.failed, 0);
  } finally {
    globalThis.fetch = originalFetch;
    await rm(dir, { recursive: true, force: true });
  }
});

test("runCrawler syncs a persistent catalog across runs", async () => {
  const dir = await mkdtemp(join(tmpdir(), "crawler-test-"));
  const sources = join(dir, "sources");
  const state = join(dir, "state");
  const out = join(dir, "out", "jobs.jsonl");
  const report = join(dir, "out", "report.json");
  const catalogDbFile = join(state, "catalog.sqlite");
  const catalogFile = join(dir, "out", "catalog.jsonl");

  await mkdir(sources);
  await mkdir(state);
  await writeFile(join(sources, "lever.json"), JSON.stringify({
    provider: "lever",
    companies: [{ identifier: "ok" }]
  }));

  let callCount = 0;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input) => {
    const url = String(input);
    if (!url.includes("api.lever.co/v0/postings/ok?mode=json")) {
      throw new Error(`unexpected url: ${url}`);
    }

    callCount += 1;
    const jobs = callCount === 1
      ? [
        { id: "1", text: "Job A", hostedUrl: "https://jobs.lever.co/ok/1" },
        { id: "2", text: "Job B", hostedUrl: "https://jobs.lever.co/ok/2" }
      ]
      : [
        { id: "2", text: "Job B Updated", hostedUrl: "https://jobs.lever.co/ok/2" }
      ];

    return new Response(JSON.stringify(jobs), { status: 200 });
  };

  try {
    await runCrawler({
      sourcesDir: sources,
      selectedProviders: ["lever"],
      concurrency: 1,
      outFile: out,
      reportFile: report,
      catalogDbFile,
      catalogFile,
      progressEveryMs: 0,
      providerConcurrency: {},
      timeoutMs: 1000,
      retries: 0
    });

    const firstCatalog = JSON.parse(`[${(await readFile(catalogFile, "utf8")).trim().split(/\r?\n/).join(",")}]`) as Array<Record<string, unknown>>;
    assert.equal(firstCatalog.length, 2);
    const firstJobB = firstCatalog.find((job) => job.job_id === "2");
    assert.ok(firstJobB);

    await runCrawler({
      sourcesDir: sources,
      selectedProviders: ["lever"],
      concurrency: 1,
      outFile: out,
      reportFile: report,
      catalogDbFile,
      catalogFile,
      progressEveryMs: 0,
      providerConcurrency: {},
      timeoutMs: 1000,
      retries: 0
    });

    const secondCatalog = JSON.parse(`[${(await readFile(catalogFile, "utf8")).trim().split(/\r?\n/).join(",")}]`) as Array<Record<string, unknown>>;
    assert.equal(secondCatalog.length, 1);
    assert.equal(secondCatalog[0]?.job_id, "2");
    assert.equal(secondCatalog[0]?.title, "Job B Updated");
    assert.equal(secondCatalog[0]?.first_seen_at, firstJobB.first_seen_at);
    assert.notEqual(secondCatalog[0]?.last_seen_at, firstJobB.last_seen_at);
  } finally {
    globalThis.fetch = originalFetch;
    await rm(dir, { recursive: true, force: true });
  }
});
