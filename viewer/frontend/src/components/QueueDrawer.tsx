import { useState } from "react";

import { useConfig, useQueue } from "../api/hooks";
import { useUiStore } from "../stores/uiStore";
import { QueueItem } from "./QueueItem";

export function QueueDrawer() {
  const isOpen = useUiStore((s) => s.isQueueDrawerOpen);
  const setQueueDrawerOpen = useUiStore((s) => s.setQueueDrawerOpen);
  const setActivePanelJobKey = useUiStore((s) => s.setActivePanelJobKey);
  const queue = useQueue();
  const config = useConfig();
  const [dismissedToApply, setDismissedToApply] = useState<Set<string>>(new Set());

  if (!isOpen) return null;

  const minScore = config.data?.scoreNotifyMinScore ?? 4;
  const toApply = (queue.data ?? []).filter(
    (item) => item.score !== null && item.score >= minScore && !dismissedToApply.has(item.id),
  );

  return (
    <>
      <div className="queue-drawer-backdrop" onClick={() => setQueueDrawerOpen(false)} />
      <div className="queue-drawer" role="dialog" aria-label="Analysis queue">
        <div className="queue-drawer-header">
          <h3>Queue</h3>
          <button type="button" onClick={() => setQueueDrawerOpen(false)}>
            Close
          </button>
        </div>

        {toApply.length > 0 && (
          <div className="to-apply-bucket">
            <h4>To Apply</h4>
            {toApply.map((item) => (
              <div key={item.id} className="to-apply-item">
                <button type="button" onClick={() => setActivePanelJobKey(item.job_key)}>
                  {item.title} — {item.score?.toFixed(1)}/5
                </button>
                <button
                  type="button"
                  onClick={() =>
                    setDismissedToApply((prev) => new Set(prev).add(item.id))
                  }
                >
                  Dismiss
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="queue-drawer-list">
          {(queue.data ?? []).length === 0 && <p>Queue is empty.</p>}
          {(queue.data ?? []).map((item) => (
            <QueueItem key={item.id} item={item} />
          ))}
        </div>
      </div>
    </>
  );
}
