import { html } from "../lib/html.js";

/**
 * @param {{ searches: Array<{ id: string, label: string }>, activeIds: string[], onToggle: (id: string) => void }} props
 */
export function SavedSearchStrip({ searches, activeIds, onToggle }) {
  if (searches.length === 0) return null;

  return html`
    <div className="saved-search-strip" role="group" aria-label="Saved searches">
      ${searches.map((search) => {
        const active = activeIds.includes(search.id);
        return html`<button
          key=${search.id}
          type="button"
          className="saved-search-chip"
          aria-pressed=${active}
          data-active=${active}
          onClick=${() => onToggle(search.id)}
        >
          ${search.label}
        </button>`;
      })}
    </div>
  `;
}
