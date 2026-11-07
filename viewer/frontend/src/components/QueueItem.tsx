import { useEffect, useState } from "react";

import { useDeleteQueueItem, useRestartQueueItem, useRetryQueueItem, useStopQueueItem } from "../api/hooks";
import { useUiStore } from "../stores/uiStore";
import type { QueueItem as QueueItemType, QueueTaskStatus } from "../types";

const STATUS_ICON: Record<QueueTaskStatus, string> = {
  todo: "○",
  running: "◐",
  done: "✓",
  error: "✕",
  permanent_error: "✕",
  retrying: "↻",
};

function formatElapsed(startedAt: string, nowMs: number): string {
  const seconds = Math.max(0, Math.floor((nowMs - new Date(startedAt).getTime()) / 1000));
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

interface Props {
  item: QueueItemType;
}

export function QueueItem({ item }: Props) {
  const retry = useRetryQueueItem();
  const stop = useStopQueueItem();
  const restart = useRestartQueueItem();
  const remove = useDeleteQueueItem();
  const setActivePanelJobKey = useUiStore((s) => s.setActivePanelJobKey);

  const [now, setNow] = useState(Date.now());
  const isRunning = item.status === "running" || item.status === "todo";

  useEffect(() => {
    if (!isRunning) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [isRunning]);

  const runningSubtask = item.subtasks.find((s) => s.status === "running" && s.started_at);
  const canRetry = item.status === "error" || item.status === "permanent_error";
  const canStop = item.status === "running" || item.status === "todo";

  return (
    <div className="queue-item">
      <div className="queue-item-header">
        <button
          type="button"
          className="queue-item-title"
          onClick={() => setActivePanelJobKey(item.job_key)}
        >
          {item.title}
        </button>
        <span className="pill">{item.mode}</span>
        <span className={`queue-item-status queue-item-status-${item.status}`}>{item.status}</span>
      </div>
      <p className="queue-item-company">{item.company}</p>

      <div className="queue-item-subtasks">
        {item.subtasks.map((subtask) => (
          <div key={subtask.id} className={`queue-subtask queue-subtask-${subtask.status}`}>
            <span className="queue-subtask-icon">{STATUS_ICON[subtask.status]}</span>
            <span className="queue-subtask-label">{subtask.label}</span>
          </div>
        ))}
      </div>

      {runningSubtask?.started_at && (
        <p className="queue-item-elapsed mono">{formatElapsed(runningSubtask.started_at, now)}</p>
      )}

      <div className="queue-item-actions">
        {canRetry && (
          <button type="button" onClick={() => retry.mutate(item.id)}>
            Retry
          </button>
        )}
        {canStop && (
          <button type="button" onClick={() => stop.mutate(item.id)}>
            Stop
          </button>
        )}
        <button type="button" onClick={() => restart.mutate(item.id)}>
          Restart
        </button>
        <button type="button" onClick={() => remove.mutate(item.id)}>
          Dismiss
        </button>
      </div>
    </div>
  );
}
