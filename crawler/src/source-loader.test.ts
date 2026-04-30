import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { loadSourceFile, parseProviderList, sourceKey } from "./source-loader.js";

test("parseProviderList supports all and comma-separated providers", () => {
  assert.deepEqual(parseProviderList("all"), ["ashby", "bamboohr", "greenhouse", "lever", "teamtailor", "workable", "workday"]);
  assert.deepEqual(parseProviderList("lever,greenhouse"), ["lever", "greenhouse"]);
});

test("parseProviderList rejects unsupported providers", () => {
  assert.throws(() => parseProviderList("unknown"), /Unsupported provider/);
});

test("sourceKey handles identifier and Workday sources", () => {
  assert.equal(sourceKey("lever", { identifier: "openai" }), "openai");
  assert.equal(sourceKey("workday", { tenant: "acme", shard: "wd5", site: "careers" }), "acme/wd5/careers");
});

test("loadSourceFile treats missing provider files as empty", async () => {
  const dir = await mkdtemp(join(tmpdir(), "source-loader-test-"));
  assert.deepEqual(await loadSourceFile(dir, "workable"), { provider: "workable", companies: [] });
});
