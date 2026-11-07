import { useCallback, useEffect, useState } from "../../vendor/react.js";

/**
 * Fetch-and-hold hook. Previous data stays in place while a new fetch runs
 * (no empty flash on page change); errors keep the last good data.
 *
 * @template T
 * @param {() => Promise<T>} fetcher
 * @param {{ deps?: unknown[], intervalMs?: number | null, enabled?: boolean }} [options]
 * @returns {{ data: T | undefined, error: any, isLoading: boolean, isFetching: boolean, refresh: () => void }}
 */
export function useResource(fetcher, { deps = [], intervalMs = null, enabled = true } = {}) {
  const [state, setState] = useState(/** @type {{ data?: T, error: any, fetching: boolean }} */ ({ error: null, fetching: false }));
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;
    const run = () =>
      fetcher().then(
        (data) => {
          if (!cancelled) setState((s) => ({ ...s, data, error: null, fetching: false }));
        },
        (error) => {
          if (!cancelled) setState((s) => ({ ...s, error, fetching: false }));
        },
      );
    setState((s) => ({ ...s, fetching: true }));
    run();
    const id = intervalMs ? setInterval(run, intervalMs) : null;
    return () => {
      cancelled = true;
      if (id) clearInterval(id);
    };
    // The fetcher is intentionally excluded: callers list what changes it in deps.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, intervalMs, tick, ...deps]);

  const refresh = useCallback(() => setTick((t) => t + 1), []);
  return {
    data: state.data,
    error: state.error,
    isLoading: state.fetching && state.data === undefined,
    isFetching: state.fetching,
    refresh,
  };
}
