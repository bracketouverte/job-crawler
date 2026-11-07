import { useEffect, useRef, useState } from "../../vendor/react.js";
import { api } from "../lib/api.js";

const POLL_MS = 2000;

/**
 * Polls one match run until it completes or fails, then calls onFinished once.
 * @param {string | null} runId
 * @param {(manifest: { status: string, error: string | null }) => void} onFinished
 * @returns {{ status: string | null }}
 */
export function useRun(runId, onFinished) {
  const [status, setStatus] = useState(/** @type {string | null} */ (null));
  const finishedRef = useRef(onFinished);
  finishedRef.current = onFinished;

  useEffect(() => {
    if (!runId) {
      setStatus(null);
      return undefined;
    }
    let cancelled = false;
    let timer = null;
    const check = async () => {
      try {
        const manifest = await api.get(`/match-runs/${runId}`);
        if (cancelled) return;
        setStatus(manifest.status);
        if (manifest.status === "completed" || manifest.status === "failed") {
          finishedRef.current(manifest);
          return;
        }
      } catch (error) {
        if (cancelled) return;
        finishedRef.current({ status: "failed", error: /** @type {Error} */ (error).message });
        return;
      }
      timer = setTimeout(check, POLL_MS);
    };
    check();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [runId]);

  return { status };
}
