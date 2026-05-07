import { readFile, writeFile } from "node:fs/promises";
import type { HiddenJobsState, ScoreNotificationsState } from "./types.js";
import {
  HIDDEN_JOBS_PATH,
  SCORE_NOTIFICATIONS_PATH,
  DISCORD_WEBHOOK_URL,
  SCORE_NOTIFY_MIN_SCORE,
} from "./config.js";
import { companyLogoUrl, companyWebsite, normalizeLabel, jobMode, jobCompensation, decisionEmoji } from "./company.js";
import { analysisScore5 } from "./analysis.js";
import { selectJobUrlStatement } from "./db.js";

export async function readScoreNotifications(): Promise<ScoreNotificationsState> {
  try {
    const raw = await readFile(SCORE_NOTIFICATIONS_PATH, "utf8");
    const parsed = JSON.parse(raw) as Partial<ScoreNotificationsState>;
    return { sent: parsed.sent && typeof parsed.sent === "object" ? parsed.sent : {} };
  } catch {
    return { sent: {} };
  }
}

export async function writeScoreNotifications(state: ScoreNotificationsState): Promise<void> {
  await writeFile(SCORE_NOTIFICATIONS_PATH, `${JSON.stringify(state, null, 2)}\n`, "utf8");
}

export async function notifyDiscordForScore(row: Record<string, unknown>, runId: string): Promise<boolean> {
  if (!DISCORD_WEBHOOK_URL || !Number.isFinite(SCORE_NOTIFY_MIN_SCORE)) {
    return false;
  }
  const analysis = row.analysis;
  const score = analysisScore5(analysis);
  if (score === null || score < SCORE_NOTIFY_MIN_SCORE) {
    return false;
  }
  if (typeof row.provider !== "string" || typeof row.source_key !== "string" || typeof row.job_id !== "string") {
    return false;
  }

  const key = `${row.provider}|${row.source_key}|${row.job_id}`;
  const notifications = await readScoreNotifications();
  if (notifications.sent[key]?.score_5 >= score) {
    return false;
  }

  const title = String(row.title ?? "Job");
  const company = String(row.company ?? row.source_key);
  const dbJobUrl = (row.job_url == null && row.url == null)
    ? (selectJobUrlStatement.get(row.provider, row.source_key, row.job_id) as { job_url: string | null } | undefined)?.job_url ?? ""
    : "";
  const jobUrl = String(row.job_url ?? row.url ?? dbJobUrl);
  const thumbnailUrl = companyLogoUrl(company);
  const companyUrl = companyWebsite(company);
  const roleSummary = (analysis as { role_summary?: Record<string, unknown> } | null)?.role_summary ?? {};
  const tldr   = roleSummary.tldr   ? String(roleSummary.tldr)   : null;
  const domain = roleSummary.domain ? String(roleSummary.domain) : null;
  const validJobUrl = jobUrl.startsWith("http://") || jobUrl.startsWith("https://") ? jobUrl : undefined;
  const embed = {
    ...(companyUrl ? { author: { name: company, url: companyUrl } } : {}),
    title,
    url: validJobUrl,
    color: 3066993,
    ...(tldr ? { description: tldr } : {}),
    ...(thumbnailUrl ? { thumbnail: { url: thumbnailUrl } } : {}),
    fields: [
      { name: "Score", value: `${score.toFixed(1)}/5`, inline: true },
      { name: "Company", value: company || "n/a", inline: true },
      { name: "Location", value: normalizeLabel(row.location as string | null | undefined) || "n/a", inline: true },
      { name: "Mode", value: jobMode(row.location as string | null | undefined, row.employment_type as string | null | undefined), inline: true },
      { name: "Compensation", value: jobCompensation(row.compensation as string | null | undefined), inline: true },
      ...(domain ? [{ name: "Domain", value: domain, inline: true }] : []),
      { name: "Decision", value: decisionEmoji(score), inline: false },
    ],
  };

  const response = await fetch(DISCORD_WEBHOOK_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username: "Job Scanner",
      embeds: [embed],
      allowed_mentions: { parse: [] },
    }),
  });

  if (!response.ok) {
    throw new Error(`Discord webhook failed with status ${response.status}`);
  }

  notifications.sent[key] = {
    score_5: score,
    notified_at: new Date().toISOString(),
    run_id: runId,
  };
  await writeScoreNotifications(notifications);
  return true;
}

export async function readHiddenJobs(): Promise<Set<string>> {
  try {
    const raw = await readFile(HIDDEN_JOBS_PATH, "utf8");
    const parsed = JSON.parse(raw) as Partial<HiddenJobsState>;
    return new Set(Array.isArray(parsed.hidden) ? parsed.hidden.filter((key): key is string => typeof key === "string") : []);
  } catch {
    return new Set();
  }
}

export async function writeHiddenJobs(hidden: Set<string>): Promise<void> {
  await writeFile(
    HIDDEN_JOBS_PATH,
    `${JSON.stringify({ hidden: [...hidden].sort(), updated_at: new Date().toISOString() }, null, 2)}\n`,
    "utf8",
  );
}
