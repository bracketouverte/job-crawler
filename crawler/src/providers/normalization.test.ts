import assert from "node:assert/strict";
import test from "node:test";
import { normalizeAshbyJob } from "./ashby.js";
import { normalizeBambooJob } from "./bamboohr.js";
import { normalizeGreenhouseJob } from "./greenhouse.js";
import { normalizeLeverJob } from "./lever.js";
import { normalizeTeamtailorJob } from "./teamtailor.js";
import { normalizeWorkableJob } from "./workable.js";
import { normalizeWorkdayJob, parseWorkdayPostedAt } from "./workday.js";

const fetchedAt = "2026-04-15T00:00:00.000Z";

test("normalizes Ashby jobs", () => {
  const job = normalizeAshbyJob("acme", {
    id: "abc",
    title: "Engineer",
    location: "Remote",
    employmentType: "FullTime",
    department: "Engineering",
    workplaceType: "Remote",
    publishedAt: "2026-04-10T09:00:00.000Z",
    jobUrl: "https://jobs.ashbyhq.com/acme/abc"
  }, fetchedAt);

  assert.equal(job.provider, "ashby");
  assert.equal(job.job_id, "abc");
  assert.equal(job.department, "Engineering");
  assert.equal(job.office, "Remote");
  assert.equal(job.updated_at, "2026-04-10T09:00:00.000Z");
  assert.equal(job.job_url, "https://jobs.ashbyhq.com/acme/abc");
});

test("normalizes BambooHR jobs", () => {
  const job = normalizeBambooJob("acme", {
    id: 42,
    jobOpeningName: "Designer",
    location: "Paris",
    departmentLabel: "Product"
  }, fetchedAt);

  assert.equal(job.job_id, "42");
  assert.equal(job.department, "Product");
  assert.equal(job.job_url, "https://acme.bamboohr.com/careers/42/detail");
});

test("normalizes Greenhouse jobs", () => {
  const job = normalizeGreenhouseJob("acme", {
    id: 123,
    title: "PM",
    location: { name: "NYC" },
    absolute_url: "https://boards.greenhouse.io/acme/jobs/123",
    departments: [{ name: "Product" }],
    offices: [{ name: "HQ" }],
    language: "en"
  }, fetchedAt);

  assert.equal(job.job_id, "123");
  assert.equal(job.department, "Product");
  assert.equal(job.office, "HQ");
});

test("normalizes Lever jobs", () => {
  const job = normalizeLeverJob("acme", {
    id: "abc",
    text: "Account Executive",
    hostedUrl: "https://jobs.lever.co/acme/abc",
    categories: { location: "London", commitment: "Full-time", team: "Sales" },
    createdAt: 1760000000000
  }, fetchedAt);

  assert.equal(job.title, "Account Executive");
  assert.equal(job.employment_type, "Full-time");
  assert.equal(job.department, "Sales");
});

test("normalizes Teamtailor RSS items", () => {
  const job = normalizeTeamtailorJob("acme", {
    title: "Support",
    link: "https://acme.teamtailor.com/jobs/1",
    guid: "1",
    pubDate: "Wed, 15 Apr 2026 12:00:00 GMT",
    "teamtailor:department": "CX",
    "teamtailor:location": "Remote"
  }, fetchedAt);

  assert.equal(job.job_id, "1");
  assert.equal(job.updated_at, "2026-04-15T12:00:00.000Z");
});

test("normalizes Workday jobs", () => {
  const job = normalizeWorkdayJob(
    { tenant: "acme", shard: "wd5", site: "careers" },
    "acme/wd5/careers",
    {
      title: "Analyst",
      externalPath: "/job/TORONTO-CAN/Analyst_R1",
      locationsText: "Toronto",
      jobId: "R1",
      timeType: "Full time"
    },
    fetchedAt
  );

  assert.equal(job.job_id, "R1");
  assert.equal(job.job_url, "https://acme.wd5.myworkdayjobs.com/en-US/careers/job/Analyst_R1");
});

test("normalizes Workday relative posted dates", () => {
  assert.equal(parseWorkdayPostedAt("Posted Today", fetchedAt), "2026-04-15T00:00:00.000Z");
  assert.equal(parseWorkdayPostedAt("Posted Yesterday", fetchedAt), "2026-04-14T00:00:00.000Z");
  assert.equal(parseWorkdayPostedAt("Posted 30+ Days Ago", fetchedAt), "2026-03-16T00:00:00.000Z");
});

test("normalizes Workable jobs", () => {
  const job = normalizeWorkableJob("peaksware", {
    title: "Product Manager",
    shortcode: "ABC123",
    employment_type: "Full-time",
    telecommuting: true,
    department: "Product",
    url: "https://apply.workable.com/j/ABC123",
    published_on: "2026-04-24",
    city: "Louisville",
    state: "Colorado",
    country: "United States",
    locations: [{ city: "Louisville", region: "Colorado", country: "United States" }]
  }, fetchedAt);

  assert.equal(job.provider, "workable");
  assert.equal(job.job_id, "ABC123");
  assert.equal(job.department, "Product");
  assert.equal(job.location, "Louisville, Colorado, United States");
  assert.equal(job.office, "Remote");
  assert.equal(job.updated_at, "2026-04-24");
});
