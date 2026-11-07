import { test } from "node:test";
import assert from "node:assert/strict";

import { ApiError, createApi } from "../src/lib/api.js";

function fakeFetch(response) {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url, init });
    return response;
  };
  return { fetchImpl, calls };
}

test("GET with params builds a query string and returns parsed JSON", async () => {
  const { fetchImpl, calls } = fakeFetch(new Response(JSON.stringify({ total: 1 }), { status: 200 }));
  const api = createApi(fetchImpl);
  const data = await api.get("/jobs", { params: { title: "pm", page: 2, empty: "", gone: undefined } });
  assert.deepEqual(data, { total: 1 });
  assert.equal(calls[0].url, "/api/jobs?title=pm&page=2&empty=");
});

test("non-2xx throws ApiError carrying the status and server detail", async () => {
  const { fetchImpl } = fakeFetch(new Response(JSON.stringify({ detail: "Not found" }), { status: 404 }));
  const api = createApi(fetchImpl);
  await assert.rejects(api.get("/job"), (err) => {
    assert.ok(err instanceof ApiError);
    assert.equal(err.status, 404);
    assert.equal(err.message, "Not found");
    return true;
  });
});

test("POST sends a JSON body", async () => {
  const { fetchImpl, calls } = fakeFetch(new Response("{}", { status: 200 }));
  const api = createApi(fetchImpl);
  await api.post("/match-runs", { job_keys: ["k"], mode: "claude" });
  assert.equal(calls[0].init.method, "POST");
  assert.equal(calls[0].init.headers["Content-Type"], "application/json");
  assert.equal(calls[0].init.body, JSON.stringify({ job_keys: ["k"], mode: "claude" }));
});
