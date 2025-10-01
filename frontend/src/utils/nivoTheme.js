const nivoTheme = {
  textColor: "var(--text)",
  fontSize: 12,
  axis: {
    legend: { text: { fill: "var(--muted)" } },
    ticks: { text: { fill: "var(--text)" } },
    domain: { line: { stroke: "var(--stroke)" } },
  },
  grid: { line: { stroke: "var(--stroke)" } },
  legends: { text: { fill: "var(--text)" } },
  tooltip: {
    container: {
      background: "var(--tooltip-bg)",
      color: "var(--text)",
      border: "1px solid var(--stroke)",
      borderRadius: 12,
      padding: 10,
      boxShadow: "var(--shadow)",
    },
  },
};
export default nivoTheme;
