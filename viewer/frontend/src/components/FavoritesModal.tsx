import { useState } from "react";

import { useLocalStore } from "../stores/localStore";
import { useUiStore } from "../stores/uiStore";
import { Modal } from "./Modal";

export function FavoritesModal() {
  const isOpen = useUiStore((s) => s.isFavoritesModalOpen);
  const setOpen = useUiStore((s) => s.setFavoritesModalOpen);
  const favoriteCompanies = useLocalStore((s) => s.favoriteCompanies);
  const toggleFavoriteCompany = useLocalStore((s) => s.toggleFavoriteCompany);
  const [name, setName] = useState("");

  if (!isOpen) return null;

  const handleAdd = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    toggleFavoriteCompany(name.trim());
    setName("");
  };

  return (
    <Modal title="Favorite companies" onClose={() => setOpen(false)}>
      <form onSubmit={handleAdd} className="favorites-add-form">
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Company name"
          aria-label="Add favorite company"
        />
        <button type="submit" disabled={!name.trim()}>
          Add
        </button>
      </form>
      <div className="favorites-chip-list">
        {[...favoriteCompanies].map((company) => (
          <span key={company} className="pill favorites-chip">
            {company}
            <button
              type="button"
              onClick={() => toggleFavoriteCompany(company)}
              aria-label={`Remove ${company}`}
            >
              ×
            </button>
          </span>
        ))}
        {favoriteCompanies.size === 0 && <p>No favorite companies yet.</p>}
      </div>
    </Modal>
  );
}
