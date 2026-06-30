import { cx } from "@/lib/format";

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("skeleton h-4 w-full", className)} />;
}

export function CardSkeleton() {
  return (
    <div className="card space-y-3 p-5">
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-4 w-2/3" />
      <Skeleton className="h-4 w-1/3" />
    </div>
  );
}
