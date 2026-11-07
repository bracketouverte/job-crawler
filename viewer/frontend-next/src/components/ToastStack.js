import { html } from "../lib/html.js";
import { useToast } from "../state/context.js";

export function ToastStack() {
  const { toasts, removeToast } = useToast();
  if (toasts.length === 0) return null;

  return html`
    <div className="toast-stack" role="status" aria-live="polite">
      ${toasts.map(
        (toast) => html`
          <div key=${toast.id} className=${`toast toast-${toast.kind}`}>
            <span>${toast.message}</span>
            ${toast.undo &&
            html`<button
              type="button"
              onClick=${() => {
                toast.undo();
                removeToast(toast.id);
              }}
            >
              Undo
            </button>`}
            <button type="button" className="toast-dismiss" onClick=${() => removeToast(toast.id)} aria-label="Dismiss">×</button>
          </div>
        `,
      )}
    </div>
  `;
}
