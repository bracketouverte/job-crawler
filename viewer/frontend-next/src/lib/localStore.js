/**
 * Browser-side state for hidden, visited and favourite marks. Uses the same
 * storage key and zustand-persist envelope as the old frontend so existing
 * data carries over at cutover.
 */

export const LOCAL_STORE_KEY = "job-viewer-local-store";

/**
 * @typedef {object} LocalState
 * @property {Set<string>} hiddenJobs
 * @property {Set<string>} visitedJobs
 * @property {Set<string>} favoriteCompanies
 */

function emptyState() {
  return { hiddenJobs: new Set(), visitedJobs: new Set(), favoriteCompanies: new Set() };
}

/**
 * @param {{ getItem: (k: string) => string | null }} storage
 * @returns {LocalState}
 */
export function readLocalState(storage) {
  try {
    const raw = storage.getItem(LOCAL_STORE_KEY);
    if (!raw) return emptyState();
    const state = JSON.parse(raw).state ?? {};
    return {
      hiddenJobs: new Set(state.hiddenJobs ?? []),
      visitedJobs: new Set(state.visitedJobs ?? []),
      favoriteCompanies: new Set(state.favoriteCompanies ?? []),
    };
  } catch {
    return emptyState();
  }
}

/**
 * @param {{ setItem: (k: string, v: string) => void }} storage
 * @param {LocalState} state
 */
export function writeLocalState(storage, state) {
  try {
    storage.setItem(
      LOCAL_STORE_KEY,
      JSON.stringify({
        state: {
          hiddenJobs: [...state.hiddenJobs],
          visitedJobs: [...state.visitedJobs],
          favoriteCompanies: [...state.favoriteCompanies],
        },
        version: 0,
      }),
    );
  } catch {
    // Storage unavailable (private window, blocked site data): keep working in memory.
  }
}
