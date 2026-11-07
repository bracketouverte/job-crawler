import { useCallback, useMemo, useState, useEffect } from "../vendor/react.js";
import { api } from "./lib/api.js";
import { mergeJobs } from "./lib/jobDisplay.js";
import { DEFAULT_FILTERS, filtersFromSearch, filtersToSearch, toJobsParams } from "./lib/filters.js";
import { html } from "./lib/html.js";
import { useResource } from "./hooks/useResource.js";
import { useLocalState } from "./state/localState.js";
import { useToasts } from "./state/toasts.js";
import { LocalContext, ToastContext, UiContext } from "./state/context.js";
import { AnalysisPanel } from "./components/AnalysisPanel.js";
import { FavoritesModal } from "./components/FavoritesModal.js";
import { FilterBar } from "./components/FilterBar.js";
import { Header } from "./components/Header.js";
import { JobList } from "./components/JobList.js";
import { Pagination } from "./components/Pagination.js";
import { PasteJDModal } from "./components/PasteJDModal.js";
import { QueueDrawer } from "./components/QueueDrawer.js";
import { SavedSearchStrip } from "./components/SavedSearchStrip.js";
import { ToastStack } from "./components/ToastStack.js";

const PAGE_SIZE = 50;
const SEARCH_LIMIT = 500;

/** Saved-search query mapped to the same /api/jobs parameters the old viewer sent. */
function savedSearchParams(search) {
  return {
    title: search.title,
    myLoc: search.location,
    company: search.company,
    sources: search.sources?.join(",") || undefined,
    days: search.days,
    limit: SEARCH_LIMIT,
  };
}

export function App() {
  const initial = useMemo(() => filtersFromSearch(window.location.search), []);
  const [filters, setFilters] = useState(initial.filters);
  const [activeIds, setActiveIds] = useState(initial.searches);
  const [refreshKey, setRefreshKey] = useState(0);
  const [panelJobKey, setPanelJobKey] = useState(null);
  const [queueOpen, setQueueOpen] = useState(false);
  const [pasteOpen, setPasteOpen] = useState(false);
  const [favoritesOpen, setFavoritesOpen] = useState(false);

  const local = useLocalState();
  const toasts = useToasts();

  useEffect(() => {
    window.history.replaceState(null, "", window.location.pathname + filtersToSearch(filters, activeIds));
  }, [filters, activeIds]);

  const setFilter = useCallback(
    (key, value) => setFilters((prev) => ({ ...prev, [key]: value, page: key === "page" ? value : 1 })),
    [],
  );
  const resetFilters = useCallback(() => setFilters(DEFAULT_FILTERS), []);
  const toggleSearch = useCallback(
    (id) => setActiveIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id])),
    [],
  );

  const savedSearches = useResource(() =>
    fetch("/saved-searches.json")
      .then((r) => (r.ok ? r.json() : []))
      .catch(() => []),
  );
  const activeSearches = (savedSearches.data ?? []).filter((s) => activeIds.includes(s.id));
  const searchesActive = activeSearches.length > 0;

  const params = toJobsParams(filters, PAGE_SIZE);
  const jobs = useResource(() => api.get("/jobs", { params }), {
    deps: [JSON.stringify(params), refreshKey],
    enabled: !searchesActive,
  });

  const searchKey = activeSearches.map((s) => s.id).join(",");
  const searchJobs = useResource(
    () =>
      Promise.all(activeSearches.map((s) => api.get("/jobs", { params: savedSearchParams(s) }))).then((lists) => {
        const merged = mergeJobs(lists.map((l) => l.jobs));
        return { jobs: merged, total: merged.length };
      }),
    { deps: [searchKey, refreshKey], enabled: searchesActive },
  );

  const queue = useResource(() => api.get("/queue"), {
    deps: [queueOpen],
    intervalMs: queueOpen ? 3000 : 15000,
  });

  const refreshJobs = useCallback(() => setRefreshKey((k) => k + 1), []);

  const ui = {
    panelJobKey,
    openPanel: setPanelJobKey,
    closePanel: () => setPanelJobKey(null),
    queueOpen,
    setQueueOpen,
    pasteOpen,
    setPasteOpen,
    openPasteJD: () => setPasteOpen(true),
    favoritesOpen,
    setFavoritesOpen,
    refreshJobs,
    refreshQueue: queue.refresh,
  };

  const view = searchesActive ? searchJobs : jobs;

  return html`
    <${UiContext.Provider} value=${ui}>
      <${LocalContext.Provider} value=${local}>
        <${ToastContext.Provider} value=${toasts}>
          <div className="app">
            <${Header} queue=${queue} />
            <${SavedSearchStrip}
              searches=${savedSearches.data ?? []}
              activeIds=${activeIds}
              onToggle=${toggleSearch}
            />
            <${FilterBar}
              filters=${filters}
              setFilter=${setFilter}
              resetFilters=${resetFilters}
              disabled=${searchesActive}
            />
            <${JobList}
              jobs=${view.data?.jobs}
              isLoading=${view.isLoading}
              isError=${!!view.error}
              busy=${view.isFetching}
            />
            ${!searchesActive &&
            html`<${Pagination}
              page=${filters.page}
              total=${jobs.data?.total ?? 0}
              limit=${PAGE_SIZE}
              onPageChange=${(p) => setFilter("page", p)}
            />`}
            <${AnalysisPanel} />
            <${QueueDrawer} queue=${queue} />
            <${PasteJDModal} />
            <${FavoritesModal} />
            <${ToastStack} />
          </div>
        <//>
      <//>
    <//>
  `;
}
