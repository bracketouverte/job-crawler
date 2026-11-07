import { test } from "node:test";
import assert from "node:assert/strict";

import { LOCAL_STORE_KEY, readLocalState, writeLocalState } from "../src/lib/localStore.js";

function memoryStorage(initial = {}) {
  const data = { ...initial };
  return {
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => {
      data[k] = v;
    },
    data,
  };
}

test("uses the same storage key and zustand persist shape as today", () => {
  assert.equal(LOCAL_STORE_KEY, "job-viewer-local-store");
  const storage = memoryStorage();
  writeLocalState(storage, {
    hiddenJobs: new Set(["a|b|1"]),
    visitedJobs: new Set(["a|b|2"]),
    favoriteCompanies: new Set(["Stripe"]),
  });
  assert.deepEqual(JSON.parse(storage.data[LOCAL_STORE_KEY]), {
    state: { hiddenJobs: ["a|b|1"], visitedJobs: ["a|b|2"], favoriteCompanies: ["Stripe"] },
    version: 0,
  });
});

test("reads existing persisted data back into Sets", () => {
  const storage = memoryStorage({
    [LOCAL_STORE_KEY]: JSON.stringify({
      state: { hiddenJobs: ["x|y|1"], visitedJobs: [], favoriteCompanies: ["Acme"] },
      version: 0,
    }),
  });
  const state = readLocalState(storage);
  assert.deepEqual([...state.hiddenJobs], ["x|y|1"]);
  assert.deepEqual([...state.visitedJobs], []);
  assert.deepEqual([...state.favoriteCompanies], ["Acme"]);
});

test("missing or corrupt storage yields empty sets without throwing", () => {
  for (const raw of [null, "{not json"]) {
    const storage = memoryStorage({ [LOCAL_STORE_KEY]: raw });
    const state = readLocalState(storage);
    assert.equal(state.hiddenJobs.size, 0);
    assert.equal(state.visitedJobs.size, 0);
    assert.equal(state.favoriteCompanies.size, 0);
  }
});

test("a throwing storage accessor is tolerated", () => {
  const broken = {
    getItem: () => {
      throw new Error("denied");
    },
    setItem: () => {
      throw new Error("denied");
    },
  };
  assert.equal(readLocalState(broken).hiddenJobs.size, 0);
  assert.doesNotThrow(() => writeLocalState(broken, { hiddenJobs: new Set(), visitedJobs: new Set(), favoriteCompanies: new Set() }));
});
