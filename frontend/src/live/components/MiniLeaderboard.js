import React from "react";

const { createElement } = React;

export function MiniLeaderboard({ entries = [], you = null, title = "Leaderboard" }) {
  const topFive = entries.slice(0, 5);

  const listItems = topFive.map(entry =>
    createElement(
      "li",
      {
        key: `${entry.rank}-${entry.name}`,
        style: {
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0.35rem 0.5rem",
          borderRadius: "0.5rem",
          background: "#f9fafb",
          marginBottom: "0.35rem",
        },
      },
      createElement(
        "span",
        { style: { fontWeight: 600 } },
        `${entry.rank}.`
      ),
      createElement(
        "span",
        { style: { flex: 1, marginLeft: "0.5rem", marginRight: "0.5rem" } },
        entry.name
      ),
      createElement(
        "span",
        { style: { fontVariantNumeric: "tabular-nums" } },
        entry.score
      )
    )
  );

  const youNode = you
    ? createElement(
        "div",
        {
          "aria-label": "Your standing",
          style: {
            marginTop: "0.75rem",
            padding: "0.5rem",
            borderRadius: "0.5rem",
            background: "#1d4ed8",
            color: "#ffffff",
            textAlign: "center",
            fontWeight: 600,
          },
        },
        `You • #${you.rank} • ${you.score} pts`
      )
    : null;

  return createElement(
    "aside",
    {
      "aria-label": "Mini leaderboard",
      className: "mini-leaderboard",
      style: {
        border: "1px solid #e5e7eb",
        borderRadius: "0.75rem",
        padding: "1rem",
        background: "#ffffff",
        boxShadow: "0 10px 15px -3px rgba(0,0,0,0.1)",
        maxWidth: "260px",
      },
    },
    createElement(
      "h2",
      {
        style: {
          fontSize: "1rem",
          fontWeight: 600,
          marginBottom: "0.75rem",
        },
      },
      title
    ),
    createElement("ol", { style: { listStyle: "none", margin: 0, padding: 0 } }, listItems),
    youNode
  );
}

export default MiniLeaderboard;
