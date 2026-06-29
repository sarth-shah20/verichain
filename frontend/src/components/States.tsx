import { AlertCircle, Inbox, RotateCw } from "lucide-react";

export function EmptyState({
  title,
  description,
  icon: Icon = Inbox,
  action,
}: {
  title: string;
  description?: string;
  icon?: typeof Inbox;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-white/60 px-6 py-16 text-center dark:border-slate-700 dark:bg-slate-900/40">
      <div className="rounded-full bg-slate-100 p-3 text-slate-400 dark:bg-slate-800">
        <Icon className="h-7 w-7" />
      </div>
      <h3 className="mt-4 text-lg font-semibold text-slate-800 dark:text-slate-100">
        {title}
      </h3>
      {description && (
        <p className="mt-1 max-w-md text-sm text-slate-500 dark:text-slate-400">
          {description}
        </p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function ErrorState({
  title = "Something went wrong",
  description,
  onRetry,
}: {
  title?: string;
  description?: string;
  onRetry?: () => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-red-200 bg-red-50/60 px-6 py-16 text-center dark:border-red-900/60 dark:bg-red-950/30">
      <div className="rounded-full bg-red-100 p-3 text-risk-high dark:bg-red-950">
        <AlertCircle className="h-7 w-7" />
      </div>
      <h3 className="mt-4 text-lg font-semibold text-slate-800 dark:text-slate-100">
        {title}
      </h3>
      {description && (
        <p className="mt-1 max-w-md text-sm text-slate-600 dark:text-slate-300">
          {description}
        </p>
      )}
      {onRetry && (
        <button onClick={onRetry} className="btn-secondary mt-5">
          <RotateCw className="h-4 w-4" /> Try again
        </button>
      )}
    </div>
  );
}
