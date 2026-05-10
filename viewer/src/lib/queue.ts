import { readFile, writeFile, rename } from "node:fs/promises";
import { join } from "node:path";
import { STATE_DIR, RETRY_QUEUE_PATH } from "./config.js";
import type { QueueItem } from "./types.js";

export async function readQueue(): Promise<QueueItem[]> {
  try {
    const raw = await readFile(RETRY_QUEUE_PATH, "utf8");
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export async function writeQueue(items: QueueItem[]): Promise<void> {
  const tmp = join(STATE_DIR, ".retry-queue.tmp.json");
  await writeFile(tmp, `${JSON.stringify(items, null, 2)}\n`, "utf8");
  await rename(tmp, RETRY_QUEUE_PATH);
}

export async function upsertQueueItem(item: QueueItem): Promise<void> {
  const items = await readQueue();
  const idx = items.findIndex((i) => i.id === item.id);
  if (idx >= 0) {
    items[idx] = item;
  } else {
    items.push(item);
  }
  await writeQueue(items);
}

export async function removeQueueItem(id: string): Promise<void> {
  const items = await readQueue();
  await writeQueue(items.filter((i) => i.id !== id));
}
