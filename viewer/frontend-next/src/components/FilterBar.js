import { html } from "../lib/html.js";
import { useResource } from "../hooks/useResource.js";
import { api } from "../lib/api.js";
import { DebouncedTextInput } from "./DebouncedTextInput.js";

const TIERS = ["intern", "junior", "mid", "senior"];
const EMPLOYMENT_TYPES = ["full_time", "part_time", "contract", "internship"];

function toggleInArray(list, value) {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

/**
 * @param {{ filters: any, setFilter: (key: string, value: unknown) => void, resetFilters: () => void, disabled: boolean }} props
 */
export function FilterBar({ filters, setFilter, resetFilters, disabled }) {
  const sources = useResource(() => api.get("/sources").then((d) => d.sources));

  const checkboxGroup = (legend, options, field, label = (v) => v) => html`
    <fieldset disabled=${disabled}>
      <legend>${legend}</legend>
      ${options.map(
        (option) => html`<label key=${option} className="provider-item">
          <input
            type="checkbox"
            checked=${filters[field].includes(option)}
            onChange=${() => setFilter(field, toggleInArray(filters[field], option))}
          />
          <span>${label(option)}</span>
        </label>`,
      )}
    </fieldset>
  `;

  return html`
    <div className="filter-bar" aria-disabled=${disabled}>
      <div className="filter-row filter-row-title">
        <${DebouncedTextInput}
          value=${filters.title}
          onChange=${(v) => setFilter("title", v)}
          placeholder="Job title (supports -exclude, (or,groups))"
          aria-label="Job title"
          disabled=${disabled}
        />
      </div>

      <div className="filter-row">
        <${DebouncedTextInput}
          value=${filters.myLoc}
          onChange=${(v) => setFilter("myLoc", v)}
          placeholder="Location"
          aria-label="Location"
          disabled=${disabled}
        />
        <${DebouncedTextInput}
          value=${filters.company}
          onChange=${(v) => setFilter("company", v)}
          placeholder="Company"
          aria-label="Company"
          disabled=${disabled}
        />

        <fieldset disabled=${disabled}>
          <legend>Providers</legend>
          ${(sources.data ?? []).map(
            (source) => html`<label key=${source} className="provider-item">
              <input
                type="checkbox"
                checked=${filters.sources.includes(source)}
                onChange=${() => setFilter("sources", toggleInArray(filters.sources, source))}
              />
              <span>${source}</span>
            </label>`,
          )}
        </fieldset>

        <select value=${filters.days} onChange=${(e) => setFilter("days", e.target.value)} disabled=${disabled} aria-label="Max age">
          <option value="">Any age</option>
          <option value="1">Last 24h</option>
          <option value="7">Last 7 days</option>
          <option value="30">Last 30 days</option>
        </select>
      </div>

      <div className="filter-row">
        ${checkboxGroup("Tiers", TIERS, "tiers")}
        ${checkboxGroup("Employment type", EMPLOYMENT_TYPES, "types", (t) => t.replace("_", " "))}

        <label className="provider-item">
          <input
            type="checkbox"
            checked=${filters.remote}
            disabled=${disabled}
            onChange=${(e) => setFilter("remote", e.target.checked)}
          />
          <span>Include remote</span>
        </label>

        <label className="provider-item">
          <input
            type="checkbox"
            checked=${filters.evaluated}
            disabled=${disabled}
            onChange=${(e) => setFilter("evaluated", e.target.checked)}
          />
          <span>Evaluated only</span>
        </label>

        <select value=${filters.score} onChange=${(e) => setFilter("score", e.target.value)} disabled=${disabled} aria-label="Score filter">
          <option value="">Any score</option>
          <option value="none">Unscored</option>
          <option value="4plus">4.0+</option>
        </select>
      </div>

      <div className="filter-row">
        <${DebouncedTextInput}
          value=${filters.inc}
          onChange=${(v) => setFilter("inc", v)}
          placeholder="Must include keywords"
          aria-label="Include keywords"
          disabled=${disabled}
        />
        <${DebouncedTextInput}
          value=${filters.exc}
          onChange=${(v) => setFilter("exc", v)}
          placeholder="Must exclude keywords"
          aria-label="Exclude keywords"
          disabled=${disabled}
        />
        <button type="button" onClick=${resetFilters}>Clear all</button>
      </div>
    </div>
  `;
}
