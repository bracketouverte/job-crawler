import { api } from "../lib/api.js";
import { html } from "../lib/html.js";
import { useResource } from "../hooks/useResource.js";
import { useToast, useUi } from "../state/context.js";

const ACTIVE_STATUSES = ["todo", "running", "retrying"];

/** @param {{ queue: { data: any[] | undefined } }} props */
export function Header({ queue }) {
  const ui = useUi();
  const { addToast } = useToast();
  const crawlStatus = useResource(() => api.get("/crawl-status"), { intervalMs: 30000 });
  const autoAnalyzer = useResource(() => api.get("/auto-analyzer"), { intervalMs: 5000 });

  const activeCount = (queue.data ?? []).filter((item) => ACTIVE_STATUSES.includes(item.status)).length;

  const togglePaused = async () => {
    const paused = !autoAnalyzer.data.paused;
    try {
      await api.post("/auto-analyzer", { paused });
      addToast({ message: paused ? "Auto-analyzer paused." : "Auto-analyzer resumed.", kind: "success" });
    } catch (error) {
      addToast({ message: `Failed to change auto-analyzer: ${error.message}`, kind: "error" });
    }
    autoAnalyzer.refresh();
  };

  const status = crawlStatus.data;
  return html`
    <header className="app-header">
      <div>
        <h1>Job Viewer</h1>
        ${status &&
        html`<p className="crawl-status mono">
          ${status.active ? "Crawl active" : `Next crawl: ${status.next_run}`}
        </p>`}
      </div>
      <div className="app-header-actions">
        ${autoAnalyzer.data &&
        html`<button type="button" onClick=${togglePaused} aria-pressed=${!autoAnalyzer.data.paused}>
          Auto-analyzer: ${autoAnalyzer.data.paused ? "paused" : "running"}
        </button>`}
        <button type="button" onClick=${() => ui.setFavoritesOpen(true)}>Favorites</button>
        <button type="button" onClick=${() => ui.setQueueOpen(!ui.queueOpen)} aria-expanded=${ui.queueOpen}>
          Queue${activeCount > 0 ? ` (${activeCount})` : ""}
        </button>
      </div>
    </header>
  `;
}
