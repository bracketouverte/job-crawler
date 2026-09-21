import { createReadStream, createWriteStream } from "node:fs";
import { mkdir, rename } from "node:fs/promises";
import { dirname } from "node:path";
import { pipeline } from "node:stream/promises";
import { Readable } from "node:stream";
import { NormalizedJob } from "./types.js";
import { extractCompensation, applySalaryToJob, detectWorkMode } from "./compensation.js";
import { createHttpClient } from "./http.js";
import { matchesTitleFilter } from "./title-filter.js";

type EnrichmentResult = {
  enriched: number;
  skipped: number;
  failed: number;
  total: number;
};

/**
 * Fetch a job page and extract salary from its HTML content.
 * Strips HTML tags to get plain text for salary extraction.
 */
async function fetchAndExtractSalary(url: string, getText: (url: string) => Promise<string>): Promise<{ min: number | null; max: number | null; currency: string | null; period: string | null; location: string | null; isEstimated: boolean; rawText: string | null }> {
  const html = await getText(url);
  // Strip HTML tags to get plain text
  const text = html
    .replace(/<script[^>]*>[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[^>]*>[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/\s+/g, " ")
    .trim();

  return extractCompensation(text);
}

/**
 * Check if a job already has salary data.
 */
function hasSalaryData(job: NormalizedJob): boolean {
  return job.salary_min !== null || job.salary_max !== null;
}

/**
 * Enrich jobs with salary data by fetching their job pages.
 * 
 * @param jobs - Array of jobs to enrich
 * @param concurrency - Max concurrent page fetches (default: 4)
 * @param delayMs - Delay between batches in ms (default: 500)
 * @returns Enrichment results
 */
export async function enrichJobsWithSalary(
  jobs: NormalizedJob[],
  options: { concurrency?: number; delayMs?: number; titleKeywords?: string[] } = {}
): Promise<{ jobs: NormalizedJob[]; results: EnrichmentResult }> {
  const concurrency = options.concurrency ?? 4;
  const delayMs = options.delayMs ?? 500;
  const titleKeywords = options.titleKeywords ?? [];

  const client = createHttpClient({ timeoutMs: 15000, retries: 1 });
  const enrichedJobs = [...jobs];
  let enriched = 0;
  let skipped = 0;
  let failed = 0;

  // Filter jobs that need enrichment (have URL but no salary)
  let toEnrich = enrichedJobs.filter((job) => job.job_url && !hasSalaryData(job));

  // Apply title filter if keywords are provided
  if (titleKeywords.length > 0) {
    toEnrich = toEnrich.filter((job) => matchesTitleFilter(job.title, titleKeywords));
  }

  skipped = jobs.length - toEnrich.length;

  if (toEnrich.length === 0) {
    return {
      jobs: enrichedJobs,
      results: { enriched: 0, skipped, failed: 0, total: jobs.length },
    };
  }

  console.log(`[salary-enricher] Enriching ${toEnrich.length}/${jobs.length} jobs with salary data...`);

  // Process in batches with controlled concurrency
  let active = 0;
  let next = 0;

  await new Promise<void>((resolve) => {
    const trySchedule = (): void => {
      while (active < concurrency && next < toEnrich.length) {
        const idx = next++;
        const job = toEnrich[idx]!;
        active++;

        const originalIndex = enrichedJobs.indexOf(job);

        client
          .getText(job.job_url!)
          .then((html) => {
            // Strip HTML tags to get plain text
            const text = html
              .replace(/<script[^>]*>[\s\S]*?<\/script>/gi, " ")
              .replace(/<style[^>]*>[\s\S]*?<\/style>/gi, " ")
              .replace(/<[^>]+>/g, " ")
              .replace(/&nbsp;/g, " ")
              .replace(/&amp;/g, "&")
              .replace(/&lt;/g, "<")
              .replace(/&gt;/g, ">")
              .replace(/\s+/g, " ")
              .trim();

            const salary = extractCompensation(text);
            const workMode = detectWorkMode(text);
            if (salary.min !== null || workMode !== null) {
              const currentJob = enrichedJobs[originalIndex];
              if (!currentJob) return;
              let updatedJob = currentJob;
              if (salary.min !== null) {
                updatedJob = applySalaryToJob(updatedJob, salary);
              }
              if (workMode !== null) {
                updatedJob = { ...updatedJob, work_mode: workMode };
              }
              enrichedJobs[originalIndex] = updatedJob;
              if (salary.min !== null) {
                enriched++;
                if (enriched % 10 === 0) {
                  console.log(`[salary-enricher] Progress: ${enriched}/${toEnrich.length} enriched`);
                }
              }
            }
          })
          .catch((error) => {
            failed++;
            if (failed <= 5) {
              console.log(`[salary-enricher] Failed to fetch ${job.job_url}: ${error.message}`);
            }
          })
          .finally(() => {
            active--;
            if (next < toEnrich.length) {
              trySchedule();
            } else if (active === 0) {
              resolve();
            }
          });
      }
      if (next >= toEnrich.length && active === 0) resolve();
    };
    trySchedule();
  });

  console.log(`[salary-enricher] Done: ${enriched} enriched, ${failed} failed, ${skipped} skipped (already had salary or no URL)`);

  return {
    jobs: enrichedJobs,
    results: { enriched, skipped, failed, total: jobs.length },
  };
}

/**
 * Read jobs from a JSONL file.
 */
export async function readJobsJsonl(filePath: string): Promise<NormalizedJob[]> {
  const fs = await import("node:fs/promises");
  const content = await fs.readFile(filePath, "utf-8");
  return content
    .split(/\r?\n/)
    .filter((line) => line.trim())
    .map((line) => JSON.parse(line) as NormalizedJob);
}

/**
 * Write jobs to a JSONL file atomically.
 */
export async function writeJobsJsonl(filePath: string, jobs: NormalizedJob[]): Promise<void> {
  await mkdir(dirname(filePath), { recursive: true });
  const tempPath = `${filePath}.tmp`;
  const lines = jobs.map((job) => JSON.stringify(job));
  await pipeline(
    Readable.from(lines.map((line) => `${line}\n`)),
    createWriteStream(tempPath)
  );
  await rename(tempPath, filePath);
}
