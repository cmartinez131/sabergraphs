import React from "react";
export default function StatusPill({ label = "Unknown", state = "warn" }) {
  return (
    <span className={`status-pill ${state}`}>
      <span className="dot" />
      {label}
    </span>
  );
}
