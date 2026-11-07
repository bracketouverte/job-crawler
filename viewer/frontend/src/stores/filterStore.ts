import { create } from "zustand";

export interface FilterState {
  title: string;
  myLoc: string;
  remote: boolean;
  days: string;
  company: string;
  sources: string[];
  tiers: string[];
  types: string[];
  score: "none" | "4plus" | "";
  evaluated: boolean;
  inc: string;
  exc: string;
  favCompanies: string[];
  page: number;
}

const DEFAULT_STATE: FilterState = {
  title: "",
  myLoc: "",
  remote: true,
  days: "",
  company: "",
  sources: [],
  tiers: [],
  types: [],
  score: "",
  evaluated: false,
  inc: "",
  exc: "",
  favCompanies: [],
  page: 1,
};

function readFromUrl(): FilterState {
  const params = new URLSearchParams(window.location.search);
  return {
    title: params.get("title") ?? DEFAULT_STATE.title,
    myLoc: params.get("myLoc") ?? DEFAULT_STATE.myLoc,
    remote: params.get("remote") !== "0",
    days: params.get("days") ?? DEFAULT_STATE.days,
    company: params.get("company") ?? DEFAULT_STATE.company,
    sources: params.get("sources")?.split(",").filter(Boolean) ?? [],
    tiers: params.get("tiers")?.split(",").filter(Boolean) ?? [],
    types: params.get("types")?.split(",").filter(Boolean) ?? [],
    score: (params.get("score") as FilterState["score"]) ?? "",
    evaluated: params.get("evaluated") === "1",
    inc: params.get("inc") ?? "",
    exc: params.get("exc") ?? "",
    favCompanies: params.get("favCompanies")?.split(",").filter(Boolean) ?? [],
    page: Number(params.get("page")) || 1,
  };
}

function writeToUrl(state: FilterState): void {
  const params = new URLSearchParams();
  if (state.title) params.set("title", state.title);
  if (state.myLoc) params.set("myLoc", state.myLoc);
  if (!state.remote) params.set("remote", "0");
  if (state.days) params.set("days", state.days);
  if (state.company) params.set("company", state.company);
  if (state.sources.length) params.set("sources", state.sources.join(","));
  if (state.tiers.length) params.set("tiers", state.tiers.join(","));
  if (state.types.length) params.set("types", state.types.join(","));
  if (state.score) params.set("score", state.score);
  if (state.evaluated) params.set("evaluated", "1");
  if (state.inc) params.set("inc", state.inc);
  if (state.exc) params.set("exc", state.exc);
  if (state.favCompanies.length) params.set("favCompanies", state.favCompanies.join(","));
  if (state.page > 1) params.set("page", String(state.page));

  // ?searches= is managed separately by the saved-search strip; preserve it here.
  const existingSearches = new URLSearchParams(window.location.search).get("searches");
  if (existingSearches) params.set("searches", existingSearches);

  const query = params.toString();
  const url = query ? `${window.location.pathname}?${query}` : window.location.pathname;
  window.history.replaceState(null, "", url);
}

interface FilterStore extends FilterState {
  setFilter: <K extends keyof FilterState>(key: K, value: FilterState[K]) => void;
  resetFilters: () => void;
}

export const useFilterStore = create<FilterStore>((set) => ({
  ...readFromUrl(),
  setFilter: (key, value) =>
    set((state) => {
      const patch: Partial<FilterState> = { [key]: value };
      // Changing any filter except an explicit page change resets pagination.
      if (key !== "page") patch.page = 1;
      writeToUrl({ ...state, ...patch });
      return patch;
    }),
  resetFilters: () => {
    writeToUrl(DEFAULT_STATE);
    set(DEFAULT_STATE);
  },
}));
