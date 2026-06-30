import type { VeriChainApi } from "./types";
import { RealVeriChainApi } from "./realClient";

// ---------------------------------------------------------------------------
// The app always talks to the live backend. Point it at a different host with
// VITE_API_BASE_URL (defaults to http://localhost:8000).
// ---------------------------------------------------------------------------

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export const api: VeriChainApi = new RealVeriChainApi(API_BASE_URL);

export * from "./types";
