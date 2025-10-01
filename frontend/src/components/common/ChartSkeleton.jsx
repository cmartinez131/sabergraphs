import React from "react";
export default function ChartSkeleton() {
  return (
    <div className="chart-skeleton">
      {[...Array(8)].map((_, i) => (
        <div key={i} className="bar">
          <div className="fill" style={{ animationDelay: `${i * 120}ms` }} />
        </div>
      ))}
    </div>
  );
}
