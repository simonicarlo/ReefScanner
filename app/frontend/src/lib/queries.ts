import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { api } from "./api";
import type { EventFilters, Job, JobProgress, Verdict } from "./types";

export const keys = {
  projects: ["projects"] as const,
  project: (id: number) => ["project", id] as const,
  defaults: ["config-defaults"] as const,
  jobs: (projectId: number) => ["jobs", projectId] as const,
  job: (id: number) => ["job", id] as const,
  events: (jobId: number, filters: EventFilters) =>
    ["events", jobId, filters] as const,
  classes: (jobId: number) => ["classes", jobId] as const,
  species: (jobId: number) => ["species", jobId] as const,
  event: (id: number) => ["event", id] as const,
};

export const useProjects = () =>
  useQuery({ queryKey: keys.projects, queryFn: api.listProjects });

export const useProject = (id: number) =>
  useQuery({ queryKey: keys.project(id), queryFn: () => api.getProject(id) });

export const useConfigDefaults = () =>
  useQuery({
    queryKey: keys.defaults,
    queryFn: api.configDefaults,
    staleTime: Infinity, // these change only when the engine does
  });

export const useJobs = (projectId: number) =>
  useQuery({ queryKey: keys.jobs(projectId), queryFn: () => api.listJobs(projectId) });

export const useJob = (id: number) =>
  useQuery({ queryKey: keys.job(id), queryFn: () => api.getJob(id) });

export const useEvents = (jobId: number, filters: EventFilters) =>
  useQuery({
    queryKey: keys.events(jobId, filters),
    queryFn: () => api.listEvents(jobId, filters),
    placeholderData: (prev) => prev, // keep the grid up while a filter changes
  });

export const useClasses = (jobId: number) =>
  useQuery({ queryKey: keys.classes(jobId), queryFn: () => api.listClasses(jobId) });

export const useSpecies = (jobId: number) =>
  useQuery({ queryKey: keys.species(jobId), queryFn: () => api.listSpecies(jobId) });

export const thresholdKey = (jobId: number) => ["thresholds", jobId] as const;

export const useThresholdAnalysis = (jobId: number) =>
  useQuery({
    queryKey: thresholdKey(jobId),
    queryFn: () => api.thresholdAnalysis(jobId),
  });

export function useSaveLabel(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: {
      eventId: number;
      verdict: Verdict;
      species?: string | null;
      notes?: string | null;
      tight_bbox?: number[] | null;
    }) => api.saveLabel(args.eventId, args),
    onSuccess: (updated) => {
      qc.setQueryData(keys.event(updated.id), updated);
      // The grid's counts and the species suggestions both move on a save.
      qc.invalidateQueries({ queryKey: ["events", jobId] });
      qc.invalidateQueries({ queryKey: keys.species(jobId) });
      // Every verdict moves the recommendation.
      qc.invalidateQueries({ queryKey: thresholdKey(jobId) });
    },
  });
}

export function useStartJob(projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.startJob(projectId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.jobs(projectId) });
      qc.invalidateQueries({ queryKey: keys.project(projectId) });
    },
  });
}

export function useCancelJob(projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: number) => api.cancelJob(jobId),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.jobs(projectId) }),
  });
}

/**
 * One WebSocket for the whole app, pushing progress straight into the query
 * cache so any mounted job list or header updates without polling.
 *
 * Mounted once, at the root. Reconnects with a backoff, because the socket
 * dies whenever the backend restarts — which during development is constantly.
 */
export function useJobProgressSocket(queryClient: QueryClient): void {
  const attempts = useRef(0);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let timer: number | undefined;
    let closed = false;

    const connect = () => {
      if (closed) return;
      const scheme = window.location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${scheme}://${window.location.host}/ws/jobs`);

      socket.onopen = () => {
        attempts.current = 0;
      };

      socket.onmessage = (message) => {
        let update: JobProgress;
        try {
          update = JSON.parse(message.data);
        } catch {
          return;
        }

        queryClient.setQueryData<Job>(keys.job(update.job_id), (prev) =>
          prev ? { ...prev, ...update, id: update.job_id } : prev,
        );
        queryClient.setQueriesData<Job[]>({ queryKey: ["jobs"] }, (prev) =>
          prev?.map((job) =>
            job.id === update.job_id ? { ...job, ...update, id: job.id } : job,
          ),
        );

        // A finished job means new events exist and the project's counts moved.
        if (["done", "failed", "cancelled"].includes(update.status)) {
          queryClient.invalidateQueries({ queryKey: ["events", update.job_id] });
          queryClient.invalidateQueries({ queryKey: ["jobs"] });
          queryClient.invalidateQueries({ queryKey: keys.projects });
        }
      };

      socket.onclose = () => {
        if (closed) return;
        attempts.current += 1;
        const backoff = Math.min(1000 * 2 ** (attempts.current - 1), 15000);
        timer = window.setTimeout(connect, backoff);
      };
    };

    connect();
    return () => {
      closed = true;
      window.clearTimeout(timer);
      socket?.close();
    };
  }, [queryClient]);
}
