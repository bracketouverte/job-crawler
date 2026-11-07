import { useEffect, useRef } from "../../vendor/react.js";
import { html } from "../lib/html.js";

const FOCUSABLE = 'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';

/** Dialog shell with Escape to close and Tab focus wrap. */
export function Modal({ title, onClose, children }) {
  const ref = useRef(null);
  // Latest onClose without re-running the effect (which would steal focus on every keystroke).
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === "Escape") {
        onCloseRef.current();
        return;
      }
      if (e.key === "Tab" && ref.current) {
        const focusable = Array.from(ref.current.querySelectorAll(FOCUSABLE));
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    ref.current?.focus();
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, []);

  return html`
    <div className="modal-backdrop" onClick=${onClose}></div>
    <div className="modal" role="dialog" aria-modal="true" aria-label=${title} ref=${ref} tabIndex=${-1}>
      <div className="modal-header">
        <h3>${title}</h3>
        <button type="button" onClick=${onClose}>Close</button>
      </div>
      <div className="modal-body">${children}</div>
    </div>
  `;
}
