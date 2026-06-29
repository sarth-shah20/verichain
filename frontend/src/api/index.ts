import type { VeriChainApi } from "./types";
import { MockVeriChainApi } from "./mock/mockClient";
import { RealVeriChainApi } from "./realClient";

// ---------------------------------------------------------------------------
// Single switch between the mock and real backends.
// Mock is ON unless VITE_USE_MOCK is explicitly "false".
// Flip VITE_USE_MOCK=false (+ set VITE_API_BASE_URL) to hit the real backend —
// no other code changes required.
// ---------------------------------------------------------------------------

export const USE_MOCK = import.meta.env.VITE_USE_MOCK !== "false";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export const api: VeriChainApi = USE_MOCK
  ? new MockVeriChainApi()
  : new RealVeriChainApi(API_BASE_URL);

export * from "./types";
