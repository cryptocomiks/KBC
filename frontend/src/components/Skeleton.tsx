/** Loading placeholders that shimmer in the shape of the content to come. */
export function Bone({ className = "" }: { className?: string }) {
  return <div className={`skeleton rounded-lg ${className}`} aria-hidden />;
}

export function CaseSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Loading">
      <div className="card space-y-4 p-5">
        <Bone className="h-7 w-72" />
        <Bone className="h-3 w-96 max-w-full" />
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          {Array.from({ length: 5 }, (_, i) => (
            <Bone key={i} className="h-24 rounded-xl" />
          ))}
        </div>
      </div>
      <Bone className="h-11 rounded-[var(--radius-card)]" />
      <div className="grid gap-4 md:grid-cols-3">
        {Array.from({ length: 3 }, (_, i) => (
          <div key={i} className="card space-y-3 p-5">
            <Bone className="h-4 w-40" />
            <Bone className="h-10 w-24" />
            <Bone className="h-2 w-full" />
            <Bone className="h-3 w-3/4" />
            <Bone className="h-3 w-2/3" />
          </div>
        ))}
      </div>
    </div>
  );
}

export function DashboardSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Loading">
      <div className="space-y-2 pt-4 pb-2">
        <Bone className="h-10 w-40" />
        <Bone className="h-4 w-80 max-w-full" />
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
        {Array.from({ length: 6 }, (_, i) => (
          <Bone key={i} className="h-28 rounded-xl" />
        ))}
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        {Array.from({ length: 3 }, (_, i) => (
          <Bone key={i} className="h-56 rounded-[var(--radius-card)]" />
        ))}
      </div>
      <Bone className="h-72 rounded-[var(--radius-card)]" />
    </div>
  );
}

export function BlockSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="card space-y-3 p-5" aria-busy="true" aria-label="Loading">
      <Bone className="h-5 w-48" />
      {Array.from({ length: rows }, (_, i) => (
        <Bone key={i} className="h-10 w-full rounded-xl" />
      ))}
    </div>
  );
}
