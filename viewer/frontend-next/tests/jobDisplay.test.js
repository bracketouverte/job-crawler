import { test } from "node:test";
import assert from "node:assert/strict";

import { companyName, jobKey, jobMode, mergeJobs, parseJobKey, scoreOutOf100 } from "../src/lib/jobDisplay.js";

test("workday company is the first path segment of the source key", () => {
  assert.equal(companyName({ provider: "workday", source_key: "acme/External" }), "acme");
  assert.equal(companyName({ provider: "lever", source_key: "stripe" }), "stripe");
});

test("jobMode classifies remote, hybrid and on-site", () => {
  assert.equal(jobMode("Remote - US", null), "Remote");
  assert.equal(jobMode("NYC", "Hybrid"), "Hybrid");
  assert.equal(jobMode("Office in Austin", null), "On-site");
  assert.equal(jobMode("Miami", null), "Miami");
  assert.equal(jobMode(null, null), "n/a");
});

test("job keys round-trip, keeping pipes in the job id", () => {
  const job = { provider: "lever", source_key: "acme", job_id: "a|b" };
  assert.equal(jobKey(job), "lever|acme|a|b");
  assert.deepEqual(parseJobKey("lever|acme|a|b"), { provider: "lever", source_key: "acme", job_id: "a|b" });
});

test("score converts 5-point to 100-point, null when missing", () => {
  assert.equal(scoreOutOf100(4.2), 84);
  assert.equal(scoreOutOf100(undefined), null);
  assert.equal(scoreOutOf100(null), null);
});

test("mergeJobs de-duplicates by job key, keeping first occurrence", () => {
  const a = { provider: "p", source_key: "s", job_id: "1", title: "first" };
  const b = { provider: "p", source_key: "s", job_id: "1", title: "second" };
  const c = { provider: "p", source_key: "s", job_id: "2" };
  assert.deepEqual(mergeJobs([[a, c], [b]]).map((j) => j.title ?? j.job_id), ["first", "2"]);
});
