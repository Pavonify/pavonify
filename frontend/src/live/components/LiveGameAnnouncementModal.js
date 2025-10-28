import React from "react";

const { createElement } = React;

export function LiveGameAnnouncementModal({ announcement, onJoin, onDismiss }) {
  return createElement(
    "div",
    {
      role: "dialog",
      "aria-modal": "true",
      "aria-labelledby": "live-game-modal-title",
      style: {
        position: "fixed",
        inset: 0,
        background: "rgba(15, 23, 42, 0.45)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 50,
      },
    },
    createElement(
      "div",
      {
        style: {
          width: "min(480px, 90vw)",
          background: "#ffffff",
          borderRadius: "1rem",
          padding: "1.5rem",
          boxShadow: "0 25px 50px -12px rgba(30,64,175,0.35)",
          display: "grid",
          gap: "1rem",
        },
      },
      createElement(
        "h2",
        { id: "live-game-modal-title", style: { fontSize: "1.35rem", fontWeight: 700 } },
        "Live game starting now!"
      ),
      createElement(
        "p",
        { style: { color: "#475569", margin: 0 } },
        `${announcement.hostName} just launched a live practice game for your class. You have ${announcement.questionTime} seconds per question.`
      ),
      createElement(
        "div",
        {
          style: {
            display: "flex",
            justifyContent: "space-between",
            fontWeight: 600,
            color: "#1f2937",
          },
        },
        createElement("span", null, `PIN ${announcement.pin}`),
        createElement("span", null, `Class ${announcement.classId}`)
      ),
      createElement(
        "div",
        { style: { display: "flex", gap: "0.75rem", justifyContent: "flex-end" } },
        createElement(
          "button",
          { type: "button", onClick: onDismiss },
          "Dismiss"
        ),
        createElement(
          "button",
          { type: "button", onClick: () => onJoin(announcement) },
          "Join now"
        )
      )
    )
  );
}

export default LiveGameAnnouncementModal;
