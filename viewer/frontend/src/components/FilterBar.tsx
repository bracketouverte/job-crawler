import { useSources } from "../api/hooks";
import { useFilterStore } from "../stores/filterStore";
import { DebouncedTextInput } from "./DebouncedTextInput";

const TIERS = ["intern", "junior", "mid", "senior"];
const EMPLOYMENT_TYPES = ["full_time", "part_time", "contract", "internship"];

function toggleInArray(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

interface Props {
  disabled: boolean;
}

export function FilterBar({ disabled }: Props) {
  const filters = useFilterStore();
  const setFilter = useFilterStore((s) => s.setFilter);
  const resetFilters = useFilterStore((s) => s.resetFilters);
  const sourcesQuery = useSources();

  return (
    <div className="filter-bar" aria-disabled={disabled}>
      <div className="filter-row filter-row-title">
        <DebouncedTextInput
          value={filters.title}
          onChange={(v) => setFilter("title", v)}
          placeholder="Job title (supports -exclude, (or,groups))"
          aria-label="Job title"
          disabled={disabled}
        />
      </div>

      <div className="filter-row">
        <DebouncedTextInput
          value={filters.myLoc}
          onChange={(v) => setFilter("myLoc", v)}
          placeholder="Location"
          aria-label="Location"
          disabled={disabled}
        />
        <DebouncedTextInput
          value={filters.company}
          onChange={(v) => setFilter("company", v)}
          placeholder="Company"
          aria-label="Company"
          disabled={disabled}
        />

        <fieldset disabled={disabled}>
          <legend>Providers</legend>
          {(sourcesQuery.data ?? []).map((source) => (
            <label key={source} className="provider-item">
              <input
                type="checkbox"
                checked={filters.sources.includes(source)}
                onChange={() => setFilter("sources", toggleInArray(filters.sources, source))}
              />
              <span>{source}</span>
            </label>
          ))}
        </fieldset>

        <select
          value={filters.days}
          onChange={(e) => setFilter("days", e.target.value)}
          disabled={disabled}
          aria-label="Max age"
        >
          <option value="">Any age</option>
          <option value="1">Last 24h</option>
          <option value="7">Last 7 days</option>
          <option value="30">Last 30 days</option>
        </select>
      </div>

      <div className="filter-row">
        <fieldset disabled={disabled}>
          <legend>Tiers</legend>
          {TIERS.map((tier) => (
            <label key={tier} className="provider-item">
              <input
                type="checkbox"
                checked={filters.tiers.includes(tier)}
                onChange={() => setFilter("tiers", toggleInArray(filters.tiers, tier))}
              />
              <span>{tier}</span>
            </label>
          ))}
        </fieldset>

        <fieldset disabled={disabled}>
          <legend>Employment type</legend>
          {EMPLOYMENT_TYPES.map((type) => (
            <label key={type} className="provider-item">
              <input
                type="checkbox"
                checked={filters.types.includes(type)}
                onChange={() => setFilter("types", toggleInArray(filters.types, type))}
              />
              <span>{type.replace("_", " ")}</span>
            </label>
          ))}
        </fieldset>

        <label className="provider-item">
          <input
            type="checkbox"
            checked={filters.remote}
            disabled={disabled}
            onChange={(e) => setFilter("remote", e.target.checked)}
          />
          <span>Include remote</span>
        </label>

        <label className="provider-item">
          <input
            type="checkbox"
            checked={filters.evaluated}
            disabled={disabled}
            onChange={(e) => setFilter("evaluated", e.target.checked)}
          />
          <span>Evaluated only</span>
        </label>

        <select
          value={filters.score}
          onChange={(e) => setFilter("score", e.target.value as typeof filters.score)}
          disabled={disabled}
          aria-label="Score filter"
        >
          <option value="">Any score</option>
          <option value="none">Unscored</option>
          <option value="4plus">4.0+</option>
        </select>
      </div>

      <div className="filter-row">
        <DebouncedTextInput
          value={filters.inc}
          onChange={(v) => setFilter("inc", v)}
          placeholder="Must include keywords"
          aria-label="Include keywords"
          disabled={disabled}
        />
        <DebouncedTextInput
          value={filters.exc}
          onChange={(v) => setFilter("exc", v)}
          placeholder="Must exclude keywords"
          aria-label="Exclude keywords"
          disabled={disabled}
        />
        <button type="button" onClick={resetFilters}>
          Clear all
        </button>
      </div>
    </div>
  );
}
