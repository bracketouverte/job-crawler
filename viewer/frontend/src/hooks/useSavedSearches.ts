import { useQueries } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { Job, JobsResponse, SavedSearch } from "../types";

function readActiveSearchIds(): string[] {
  const params = new URLSearchParams(window.location.search);
  return params.get("searches")?.split(",").filter(Boolean) ?? [];
}

function writeActiveSearchIds(ids: string[]): void {
  const params = new URLSearchParams(window.location.search);
  if (ids.length) {
    params.set("searches", ids.join(","));
  } else {
    params.delete("searches");
  }
  const query = params.toString();
  const url = query ? `${window.location.pathname}?${query}` : window.location.pathname;
  window.history.replaceState(null, "", url);
}

export function useSavedSearches(): SavedSearch[] {
  const [searches, setSearches] = useState<SavedSearch[]>([]);
  useEffect(() => {
    fetch("/saved-searches.json")
      .then((r) => (r.ok ? (r.json() as Promise<SavedSearch[]>) : []))
      .then(setSearches)
      .catch(() => setSearches([]));
  }, []);
  return searches;
}

export function useActiveSearchIds() {
  const [activeSearchIds, setActiveSearchIds] = useState<string[]>(readActiveSearchIds());

  const toggleSearch = (id: string) => {
    setActiveSearchIds((prev) => {
      const next = prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id];
      writeActiveSearchIds(next);
      return next;
    });
  };

  const clearSearches = () => {
    writeActiveSearchIds([]);
    setActiveSearchIds([]);
  };

  return { activeSearchIds, toggleSearch, clearSearches };
}

export function useMergedSearchJobs(activeSearches: SavedSearch[]) {
  const results = useQueries({
    queries: activeSearches.map((search) => ({
      queryKey: ["jobs-search", search.id],
      queryFn: async () => {
        const { data } = await api.get<JobsResponse>("/jobs", {
          params: {
            title: search.title,
            myLoc: search.location,
            company: search.company,
            sources: search.sources?.join(","),
            days: search.days,
            limit: 500,
          },
        });
        return data;
      },
    })),
  });

  const isLoading = results.some((r) => r.isLoading);
  const jobs: Job[] = [];
  const seen = new Set<string>();
  for (const result of results) {
    for (const job of result.data?.jobs ?? []) {
      const key = `${job.provider}|${job.source_key}|${job.job_id}`;
      if (!seen.has(key)) {
        seen.add(key);
        jobs.push(job);
      }
    }
  }
  return { jobs, isLoading, total: jobs.length };
}
