import {
  createContext,
  useCallback,
  useContext,
  useState,
} from "react";
import { CheckCircle2, Info, X, AlertTriangle } from "lucide-react";
import { cx } from "@/lib/format";

type ToastTone = "success" | "info" | "warning";

interface Toast {
  id: number;
  message: string;
  tone: ToastTone;
}

interface ToastContextValue {
  toast: (message: string, tone?: ToastTone) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

let nextId = 1;

const TONE_ICON = {
  success: CheckCircle2,
  info: Info,
  warning: AlertTriangle,
} as const;

const TONE_CLASS: Record<ToastTone, string> = {
  success: "text-risk-low",
  info: "text-pipeline2",
  warning: "text-risk-mid",
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const remove = useCallback((id: number) => {
    setToasts((list) => list.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback(
    (message: string, tone: ToastTone = "success") => {
      const id = nextId++;
      setToasts((list) => [...list, { id, message, tone }]);
      window.setTimeout(() => remove(id), 4000);
    },
    [remove]
  );

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div
        className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-full max-w-sm flex-col gap-2"
        aria-live="polite"
        aria-atomic="true"
      >
        {toasts.map((t) => {
          const Icon = TONE_ICON[t.tone];
          return (
            <div
              key={t.id}
              role="status"
              className="pointer-events-auto flex animate-slide-in items-start gap-3 rounded-lg border border-slate-200 bg-white p-3 shadow-card dark:border-slate-700 dark:bg-slate-800"
            >
              <Icon className={cx("mt-0.5 h-5 w-5 shrink-0", TONE_CLASS[t.tone])} />
              <p className="flex-1 text-sm text-slate-700 dark:text-slate-200">
                {t.message}
              </p>
              <button
                onClick={() => remove(t.id)}
                className="rounded p-0.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                aria-label="Dismiss notification"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}
