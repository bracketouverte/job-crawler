import { useAutoAnalyzer, useCrawlStatus, useQueue, useSetAutoAnalyzerPaused } from "../api/hooks";
import { useUiStore } from "../stores/uiStore";

export function Header() {
  const crawlStatus = useCrawlStatus();
  const autoAnalyzer = useAutoAnalyzer();
  const setPaused = useSetAutoAnalyzerPaused();
  const queue = useQueue();
  const isQueueDrawerOpen = useUiStore((s) => s.isQueueDrawerOpen);
  const setQueueDrawerOpen = useUiStore((s) => s.setQueueDrawerOpen);
  const setFavoritesModalOpen = useUiStore((s) => s.setFavoritesModalOpen);

  const activeCount = (queue.data ?? []).filter((item) =>
    ["todo", "running", "retrying"].includes(item.status),
  ).length;

  return (
    <header className="app-header">
      <div>
        <h1>Job Viewer</h1>
        {crawlStatus.data && (
          <p className="crawl-status mono">
            {crawlStatus.data.active ? "Crawl active" : `Next crawl: ${crawlStatus.data.next_run}`}
          </p>
        )}
      </div>
      <div className="app-header-actions">
        {autoAnalyzer.data && (
          <button
            type="button"
            onClick={() => setPaused.mutate(!autoAnalyzer.data!.paused)}
            aria-pressed={!autoAnalyzer.data.paused}
          >
            Auto-analyzer: {autoAnalyzer.data.paused ? "paused" : "running"}
          </button>
        )}
        <button type="button" onClick={() => setFavoritesModalOpen(true)}>
          Favorites
        </button>
        <button
          type="button"
          onClick={() => setQueueDrawerOpen(!isQueueDrawerOpen)}
          aria-expanded={isQueueDrawerOpen}
        >
          Queue{activeCount > 0 ? ` (${activeCount})` : ""}
        </button>
      </div>
    </header>
  );
}
