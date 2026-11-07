import { useCallback, useEffect, useRef, useState } from "../../vendor/react.js";

const AUTO_DISMISS_MS = 4000;

/**
 * @typedef {{ id: string, message: string, kind: "neutral" | "success" | "error", undo?: () => void }} Toast
 */

/** Toast queue with auto-dismiss. Every user action reports its outcome through here. */
export function useToasts() {
  const [toasts, setToasts] = useState(/** @type {Toast[]} */ ([]));
  const timers = useRef(/** @type {Map<string, ReturnType<typeof setTimeout>>} */ (new Map()));

  const removeToast = useCallback((id) => {
    clearTimeout(timers.current.get(id));
    timers.current.delete(id);
    setToasts((list) => list.filter((t) => t.id !== id));
  }, []);

  const addToast = useCallback(
    (toast) => {
      const id = crypto.randomUUID();
      setToasts((list) => [...list, { ...toast, id }]);
      timers.current.set(id, setTimeout(() => removeToast(id), AUTO_DISMISS_MS));
    },
    [removeToast],
  );

  useEffect(() => {
    const pending = timers.current;
    return () => pending.forEach((t) => clearTimeout(t));
  }, []);

  return { toasts, addToast, removeToast };
}
