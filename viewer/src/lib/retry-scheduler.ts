import { readQueue, upsertQueueItem, removeQueueItem } from "./queue.js";
import { notifyDiscordForScore } from "./notifications.js";
import type { QueueItem } from "./types.js";

const RETRY_INTERVAL_MS = 10_000;
const RETRY_BACKOFF_BASE_S = 30;

// Lazily imported to avoid circular deps (match-run imports queue, scheduler imports match-run)
async function getExecuteMatchRunFromInput(): Promise<(runId: string, mode?: string) => Promise<void>> {
  const mod = await import("./match-run.js");
  return mod.executeMatchRunFromInput;
}

async function retryDiscordItem(item: QueueItem): Promise<void> {
  const discordSub = item.subtasks.find((s) => s.id === "discord");
  if (!discordSub || !item.error) return;

  const row = JSON.parse(item.error) as Record<string, unknown>;
  try {
    await notifyDiscordForScore(row, item.id);
    await removeQueueItem(item.id);
  } catch (e) {
    const nextAttempt = item.attempt + 1;
    const isPermanent = nextAttempt >= item.max_attempts;
    await upsertQueueItem({
      ...item,
      attempt: nextAttempt,
      status: isPermanent ? "permanent_error" : "retrying",
      next_retry_at: isPermanent ? undefined : new Date(Date.now() + RETRY_BACKOFF_BASE_S * 2 ** nextAttempt * 1000).toISOString(),
      updated_at: new Date().toISOString(),
      error: e instanceof Error ? e.message : String(e),
      subtasks: item.subtasks.map((s) =>
        s.id === "discord" ? { ...s, status: isPermanent ? "permanent_error" : "error", error: e instanceof Error ? e.message : String(e) } : s,
      ),
    });
  }
}

async function tick(): Promise<void> {
  const now = Date.now();
  const items = await readQueue();
  const due = items.filter(
    (item) => item.status === "retrying" && item.next_retry_at && new Date(item.next_retry_at).getTime() <= now,
  );

  for (const item of due) {
    // Mark as running before we start so concurrent ticks don't double-fire
    await upsertQueueItem({ ...item, status: "running", updated_at: new Date().toISOString() });

    // Discord-only retry items have a single "discord" subtask and carry the row in error field
    const isDiscordOnly = item.subtasks.length === 1 && item.subtasks[0]?.id === "discord";

    if (isDiscordOnly) {
      await retryDiscordItem(item);
      continue;
    }

    try {
      const executeMatchRunFromInput = await getExecuteMatchRunFromInput();
      const runId = item.id.includes(":") ? item.id.slice(0, item.id.indexOf(":")) : item.id;
      await executeMatchRunFromInput(runId, item.mode);
      // On success executeMatchRun updates the queue item status to "done" itself
    } catch (e) {
      const nextAttempt = item.attempt + 1;
      const isPermanent = nextAttempt >= item.max_attempts;
      await upsertQueueItem({
        ...item,
        attempt: nextAttempt,
        status: isPermanent ? "permanent_error" : "retrying",
        next_retry_at: isPermanent ? undefined : new Date(Date.now() + RETRY_BACKOFF_BASE_S * 2 ** nextAttempt * 1000).toISOString(),
        updated_at: new Date().toISOString(),
        error: e instanceof Error ? e.message : String(e),
      });
    }
  }
}

export function startRetryScheduler(): void {
  setInterval(() => {
    tick().catch((e) => console.error("[retry-scheduler] tick error:", e));
  }, RETRY_INTERVAL_MS);
}
