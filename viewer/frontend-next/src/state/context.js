import { createContext, useContext } from "../../vendor/react.js";

/** App-wide UI state and actions (panel, drawers, modals, job refresh). */
export const UiContext = createContext(/** @type {any} */ (null));
/** Hidden, visited and favourite marks from useLocalState. */
export const LocalContext = createContext(/** @type {any} */ (null));
/** Toast queue; `addToast({ message, kind })` shows a toast. */
export const ToastContext = createContext(/** @type {any} */ (null));

export const useUi = () => useContext(UiContext);
export const useLocal = () => useContext(LocalContext);
export const useToast = () => useContext(ToastContext);
