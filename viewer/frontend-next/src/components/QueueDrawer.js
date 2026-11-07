import { useState } from "../../vendor/react.js";
import { html } from "../lib/html.js";
import { useResource } from "../hooks/useResource.js";
import { api } from "../lib/api.js";
import { useUi } from "../state/context.js";
import { QueueItem } from "./QueueItem.js";

/** @param {{ queue: { data: any[] | undefined, refresh: () => void } }} props */
export function QueueDrawer({ queue }) {
  const ui = useUi();
  const config = useResource(() => api.get("/config"));
  const [dismissedToApply, setDismissedToApply] = useState(/** @type {Set<string>} */ (new Set()));

  if (!ui.queueOpen) return null;

  const items = queue.data ?? [];
  const minScore = config.data?.scoreNotifyMinScore ?? 4;
  const toApply = items.filter((item) => item.score !== null && item.score >= minScore && !dismissedToApply.has(item.id));

  return html`
    <div className="queue-drawer-backdrop" onClick=${() => ui.setQueueOpen(false)}></div>
    <div className="queue-drawer" role="dialog" aria-label="Analysis queue">
      <div className="queue-drawer-header">
        <h3>Queue</h3>
        <button type="button" onClick=${() => ui.setQueueOpen(false)}>Close</button>
      </div>

      ${toApply.length > 0 &&
      html`<div className="to-apply-bucket">
        <h4>To Apply</h4>
        ${toApply.map(
          (item) => html`<div key=${item.id} className="to-apply-item">
            <button type="button" onClick=${() => ui.openPanel(item.job_key)}>${item.title} — ${item.score.toFixed(1)}/5</button>
            <button type="button" onClick=${() => setDismissedToApply((prev) => new Set(prev).add(item.id))}>Dismiss</button>
          </div>`,
        )}
      </div>`}

      <div className="queue-drawer-list">
        ${items.length === 0 && html`<p>Queue is empty.</p>`}
        ${items.map((item) => html`<${QueueItem} key=${item.id} item=${item} onChanged=${queue.refresh} />`)}
      </div>
    </div>
  `;
}
