import { useSavedSearches } from "../hooks/useSavedSearches";

interface Props {
  activeSearchIds: string[];
  onToggle: (id: string) => void;
}

export function SavedSearchStrip({ activeSearchIds, onToggle }: Props) {
  const searches = useSavedSearches();

  if (searches.length === 0) return null;

  return (
    <div className="saved-search-strip" role="group" aria-label="Saved searches">
      {searches.map((search) => (
        <button
          key={search.id}
          type="button"
          className="saved-search-chip"
          aria-pressed={activeSearchIds.includes(search.id)}
          data-active={activeSearchIds.includes(search.id)}
          onClick={() => onToggle(search.id)}
        >
          {search.label}
        </button>
      ))}
    </div>
  );
}
