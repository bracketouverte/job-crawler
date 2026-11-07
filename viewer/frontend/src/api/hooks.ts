import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { useUiStore } from "../stores/uiStore";
import type {
  AutoAnalyzerState,
  Config,
  CrawlStatus,
  HiddenJobsResponse,
  Job,
  JobsFilters,
  JobsResponse,
  MatchRunManifest,
  MatchRunResult,
  QueueItem,
} from "../types";

function parseJobKey(key: string): { provider: string; source_key: string; job_id: string } {
  const [provider, source_key, ...rest] = key.split("|");
  return { provider, source_key, job_id: rest.join("|") };
}

export function useJobs(filters: JobsFilters) {
  return useQuery({
    queryKey: ["jobs", filters],
    queryFn: async () => {
      const { data } = await api.get<JobsResponse>("/jobs", { params: filters });
      return data;
    },
  });
}

export function useJob(key: string | null) {
  return useQuery({
    queryKey: ["job", key],
    enabled: key !== null,
    queryFn: async () => {
      const { data } = await api.get<Job>("/job", { params: parseJobKey(key!) });
      return data;
    },
  });
}

export function useJobParsed(key: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ["job-parsed", key],
    enabled: enabled && key !== null,
    retry: false,
    queryFn: async () => {
      const { data } = await api.get<Record<string, unknown>>("/job-parsed", {
        params: parseJobKey(key!),
      });
      return data;
    },
  });
}

export function useSources() {
  return useQuery({
    queryKey: ["sources"],
    queryFn: async () => {
      const { data } = await api.get<{ sources: string[] }>("/sources");
      return data.sources;
    },
  });
}

export function useStats() {
  return useQuery({
    queryKey: ["stats"],
    queryFn: async () => {
      const { data } = await api.get("/stats");
      return data;
    },
  });
}

export function useStartMatchRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ job_keys, mode }: { job_keys: string[]; mode: string }) => {
      const { data } = await api.post<{ run_id: string; manifest: MatchRunManifest }>(
        "/match-runs",
        { job_keys, mode },
      );
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["queue"] });
    },
  });
}

export function useStartMatchRunWithJD() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      provider: string;
      source_key: string;
      job_id: string;
      jd_text: string;
      mode: string;
    }) => {
      const { data } = await api.post<{ run_id: string; manifest: MatchRunManifest }>(
        "/match-runs-with-jd",
        body,
      );
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["queue"] });
    },
  });
}

export function useMatchRun(id: string | null, enabled: boolean) {
  // Polls at a fixed interval while `enabled`; the caller is expected to flip
  // `enabled` to false once it observes a terminal status (completed/failed)
  // — e.g. via an effect on `data.status` — to stop polling.
  return useQuery({
    queryKey: ["match-run", id],
    enabled: enabled && id !== null,
    refetchInterval: enabled ? 2000 : false,
    queryFn: async () => {
      const { data } = await api.get<MatchRunManifest>(`/match-runs/${id}`);
      return data;
    },
  });
}

export function useMatchRunResults(id: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ["match-run-results", id],
    enabled: enabled && id !== null,
    queryFn: async () => {
      const { data } = await api.get<MatchRunResult[]>(`/match-runs/${id}/results`);
      return data;
    },
  });
}

export function useQueue() {
  const isOpen = useUiStore((s) => s.isQueueDrawerOpen);
  return useQuery({
    queryKey: ["queue"],
    refetchInterval: isOpen ? 3000 : 15000,
    queryFn: async () => {
      const { data } = await api.get<QueueItem[]>("/queue");
      return data;
    },
  });
}

export function useRetryQueueItem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const { data } = await api.post<QueueItem>(`/queue/${id}/retry`);
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["queue"] }),
  });
}

export function useStopQueueItem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const { data } = await api.post<QueueItem>(`/queue/${id}/stop`);
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["queue"] }),
  });
}

export function useRestartQueueItem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const { data } = await api.post<QueueItem>(`/queue/${id}/restart`);
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["queue"] }),
  });
}

export function useDeleteQueueItem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`/queue/${id}`);
      return id;
    },
    onMutate: async (id: string) => {
      await queryClient.cancelQueries({ queryKey: ["queue"] });
      const previous = queryClient.getQueryData<QueueItem[]>(["queue"]);
      queryClient.setQueryData<QueueItem[]>(["queue"], (old) =>
        (old ?? []).filter((item) => item.id !== id),
      );
      return { previous };
    },
    onError: (_err, _id, context) => {
      if (context?.previous) queryClient.setQueryData(["queue"], context.previous);
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["queue"] }),
  });
}

export function useAutoAnalyzer() {
  return useQuery({
    queryKey: ["auto-analyzer"],
    refetchInterval: 5000,
    queryFn: async () => {
      const { data } = await api.get<AutoAnalyzerState>("/auto-analyzer");
      return data;
    },
  });
}

export function useSetAutoAnalyzerPaused() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (paused: boolean) => {
      const { data } = await api.post<AutoAnalyzerState>("/auto-analyzer", { paused });
      return data;
    },
    onSuccess: (data) => queryClient.setQueryData(["auto-analyzer"], data),
  });
}

export function useConfig() {
  return useQuery({
    queryKey: ["config"],
    staleTime: Infinity,
    queryFn: async () => {
      const { data } = await api.get<Config>("/config");
      return data;
    },
  });
}

export function useCrawlStatus() {
  return useQuery({
    queryKey: ["crawl-status"],
    refetchInterval: 30000,
    queryFn: async () => {
      const { data } = await api.get<CrawlStatus>("/crawl-status");
      return data;
    },
  });
}

export function useBrandSearch(company: string | null) {
  return useQuery({
    queryKey: ["brand-search", company],
    enabled: !!company,
    staleTime: Infinity,
    queryFn: async () => {
      const { data } = await api.get<{ domain: string | null }>("/logo-dev/brand", {
        params: { company },
      });
      return data.domain;
    },
  });
}

export function useHiddenJobs() {
  return useQuery({
    queryKey: ["hidden-jobs"],
    queryFn: async () => {
      const { data } = await api.get<HiddenJobsResponse>("/hidden-jobs");
      return data.hidden;
    },
  });
}

export function useSetHiddenJobs() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (hidden: string[]) => {
      const { data } = await api.put<HiddenJobsResponse>("/hidden-jobs", { hidden });
      return data.hidden;
    },
    onSuccess: (hidden) => queryClient.setQueryData(["hidden-jobs"], hidden),
  });
}
