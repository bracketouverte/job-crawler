import { useState } from "../../vendor/react.js";
import { html } from "../lib/html.js";
import { useLocal, useToast, useUi } from "../state/context.js";
import { Modal } from "./Modal.js";

export function FavoritesModal() {
  const ui = useUi();
  const local = useLocal();
  const { addToast } = useToast();
  const [name, setName] = useState("");

  if (!ui.favoritesOpen) return null;

  const handleAdd = (e) => {
    e.preventDefault();
    const company = name.trim();
    if (!company) return;
    if (!local.favoriteCompanies.has(company)) local.toggleFavoriteCompany(company);
    addToast({ message: `Added ${company} to favorites.`, kind: "success" });
    setName("");
  };

  const companies = [...local.favoriteCompanies];

  return html`
    <${Modal} title="Favorite companies" onClose=${() => ui.setFavoritesOpen(false)}>
      <form onSubmit=${handleAdd} className="favorites-add-form">
        <input
          type="text"
          value=${name}
          onChange=${(e) => setName(e.target.value)}
          placeholder="Company name"
          aria-label="Add favorite company"
        />
        <button type="submit" disabled=${!name.trim()}>Add</button>
      </form>
      <div className="favorites-chip-list">
        ${companies.map(
          (company) => html`<span key=${company} className="pill favorites-chip">
            ${company}
            <button
              type="button"
              aria-label=${`Remove ${company}`}
              onClick=${() => {
                local.toggleFavoriteCompany(company);
                addToast({ message: `Removed ${company} from favorites.`, kind: "neutral" });
              }}
            >×</button>
          </span>`,
        )}
        ${companies.length === 0 && html`<p>No favorite companies yet.</p>`}
      </div>
    <//>
  `;
}
