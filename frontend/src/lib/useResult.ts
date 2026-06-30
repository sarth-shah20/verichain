import { useEffect, useState } from "react";
import { api } from "@/api";
import type { VerificationResult } from "@/api/types";
import { useStore } from "@/app/store";

interface UseResultState {
  result: VerificationResult | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

/**
 * Loads a verification result for a job id, preferring the in-memory store
 * (set during processing) and falling back to the API for deep links / reloads.
 */
export function useResult(jobId: string | undefined): UseResultState {
  const { current, currentJobId, setCurrent } = useStore();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const fromStore =
    current && jobId && currentJobId === jobId ? current : null;
  const [result, setResult] = useState<VerificationResult | null>(fromStore);

  useEffect(() => {
    if (!jobId) return;
    if (current && currentJobId === jobId) {
      setResult(current);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .getResult(jobId)
      .then((r) => {
        if (cancelled) return;
        setResult(r);
        setCurrent(jobId, r);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Could not load result.");
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, tick]);

  return { result, loading, error, reload: () => setTick((t) => t + 1) };
}
