import { createContext, useContext, useState } from "react";
import type { VerificationResult } from "@/api/types";

// NOTE: small client-state cache for the current verification result so the
// dashboard and document-detail screens share data without refetching.

interface StoreValue {
  current: VerificationResult | null;
  currentJobId: string | null;
  setCurrent: (jobId: string, r: VerificationResult | null) => void;
}

const StoreContext = createContext<StoreValue | null>(null);

export function StoreProvider({ children }: { children: React.ReactNode }) {
  const [current, setCurrentResult] = useState<VerificationResult | null>(null);
  const [currentJobId, setCurrentJobId] = useState<string | null>(null);

  const setCurrent = (jobId: string, r: VerificationResult | null) => {
    setCurrentJobId(jobId);
    setCurrentResult(r);
  };

  return (
    <StoreContext.Provider value={{ current, currentJobId, setCurrent }}>
      {children}
    </StoreContext.Provider>
  );
}

export function useStore(): StoreValue {
  const ctx = useContext(StoreContext);
  if (!ctx) throw new Error("useStore must be used within StoreProvider");
  return ctx;
}
