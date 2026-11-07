import { html } from "../lib/html.js";

/** @param {{ page: number, total: number, limit: number, onPageChange: (page: number) => void }} props */
export function Pagination({ page, total, limit, onPageChange }) {
  const totalPages = Math.max(1, Math.ceil(total / limit));

  const goTo = (p) => {
    onPageChange(p);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return html`
    <nav className="pagination" aria-label="Pagination">
      <button type="button" disabled=${page <= 1} onClick=${() => goTo(page - 1)}>Prev</button>
      <span className="mono">Page ${page} of ${totalPages}</span>
      <button type="button" disabled=${page >= totalPages} onClick=${() => goTo(page + 1)}>Next</button>
    </nav>
  `;
}
