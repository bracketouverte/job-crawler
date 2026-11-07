import { useEffect, useState } from "../../vendor/react.js";
import { api } from "../lib/api.js";
import { html } from "../lib/html.js";
import { useToast, useUi } from "../state/context.js";

const STATUS_ICON = { todo: "○", running: "◐", done: "✓", error: "✕", permanent_error: "✕", retrying: "↻" };

function formatElapsed(startedAt, nowMs) {
  const seconds = Math.max(0, Math.floor((nowMs - new Date(startedAt).getTime()) / 1000));
  return `${Math.floor(seconds / 60)}:${(seconds % 60).toString().padStart(2, "0")}`;
}

/**
 * One queue row with its status, subtasks, failure reason and actions.
 * @param {{ item: any, onChanged: () => void }} props
 */
export function QueueItem({ item, onChanged }) {
  const ui = useUi();
  const { addToast } = useToast();
  const [now, setNow] = useState(Date.now());
  const isActive = item.status === "running" || item.status === "todo";

  useEffect(() => {
    if (!isActive) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [isActive]);

  const runAction = async (verb, request) => {
    try {
      await request();
      addToast({ message: `${verb} "${item.title}".`, kind: "success" });
    } catch (error) {
      addToast({ message: `Failed to ${verb.toLowerCase()} "${item.title}": ${error.message}`, kind: "error" });
    }
    onChanged();
  };

  const runningSubtask = item.subtasks.find((s) => s.status === "running" && s.started_at);
  const canRetry = item.status === "error" || item.status === "permanent_error";
  const canStop = isActive;

  return html`
    <div className="queue-item">
      <div className="queue-item-header">
        <button type="button" className="queue-item-title" onClick=${() => ui.openPanel(item.job_key)}>${item.title}</button>
        <span className="pill">${item.mode}</span>
        <span className=${`queue-item-status queue-item-status-${item.status}`}>${item.status}</span>
      </div>
      <p className="queue-item-company">${item.company}</p>

      <div className="queue-item-subtasks">
        ${item.subtasks.map(
          (subtask) => html`<div key=${subtask.id} className=${`queue-subtask queue-subtask-${subtask.status}`}>
            <span className="queue-subtask-icon">${STATUS_ICON[subtask.status]}</span>
            <span className="queue-subtask-label">${subtask.label}</span>
          </div>`,
        )}
      </div>

      ${item.error && html`<p className="queue-item-error" role="alert">Reason: ${item.error}</p>`}
      ${runningSubtask?.started_at && html`<p className="queue-item-elapsed mono">${formatElapsed(runningSubtask.started_at, now)}</p>`}

      <div className="queue-item-actions">
        ${canRetry &&
        html`<button type="button" onClick=${() => runAction("Retried", () => api.post(`/queue/${item.id}/retry`))}>Retry</button>`}
        ${canStop &&
        html`<button type="button" onClick=${() => runAction("Stopped", () => api.post(`/queue/${item.id}/stop`))}>Stop</button>`}
        <button type="button" onClick=${() => runAction("Restarted", () => api.post(`/queue/${item.id}/restart`))}>Restart</button>
        <button type="button" onClick=${() => runAction("Dismissed", () => api.delete(`/queue/${item.id}`))}>Dismiss</button>
      </div>
    </div>
  `;
}
