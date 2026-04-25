import assert from "node:assert/strict";
import test from "node:test";
import { parseProviderList, sourceKey } from "./source-loader.js";

test("parseProviderList supports all and comma-separated providers", () => {
  assert.deepEqual(parseProviderList("all"), ["ashby", "bamboohr", "greenhouse", "lever", "teamtailor", "workday"]);
  assert.deepEqual(parseProviderList("lever,greenhouse"), ["lever", "greenhouse"]);
});

test("parseProviderList rejects unsupported providers", () => {
  assert.throws(() => parseProviderList("unknown"), /Unsupported provider/);
});

test("sourceKey handles identifier and Workday sources", () => {
  assert.equal(sourceKey("lever", { identifier: "openai" }), "openai");
  assert.equal(sourceKey("workday", { tenant: "acme", shard: "wd5", site: "careers" }), "acme/wd5/careers");
});
