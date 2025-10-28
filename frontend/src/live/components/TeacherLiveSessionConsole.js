import React, { useEffect, useMemo, useState } from "react";

import { createLiveApi } from "../api";
import { useLiveGameSocket } from "../hooks/useLiveGameSocket";

import MiniLeaderboard from "./MiniLeaderboard";
import TeacherLiveSessionForm from "./TeacherLiveSessionForm";

const { createElement } = React;

function buildWsUrl(baseUrl, path) {
  if (baseUrl) {
    return `${baseUrl.replace(/\/$/, "")}${path}`;
  }
  if (typeof window === "undefined") {
    return path;
  }
  const { protocol, host } = window.location;
  const wsProtocol = protocol === "https:" ? "wss:" : "ws:";
  return `${wsProtocol}//${host}${path}`;
}

export function TeacherLiveSessionConsole({
  classOptions = [],
  vocabListOptions = [],
  api = createLiveApi(),
  wsBaseUrl,
  questionRenderer,
}) {
  const [session, setSession] = useState(null);
  const [state, setState] = useState(null);
  const [leaderboard, setLeaderboard] = useState([]);
  const [you, setYou] = useState(null);
  const [latestQuestion, setLatestQuestion] = useState(null);
  const [lobby, setLobby] = useState({ participants: [], pin: null });
  const [statusMessage, setStatusMessage] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const wsUrl = useMemo(() => {
    if (!session) {
      return null;
    }
    return buildWsUrl(wsBaseUrl, `/ws/live-games/${session.id}/`);
  }, [session, wsBaseUrl]);

  useLiveGameSocket(wsUrl, {
    GAME_STARTED: event => {
      setStatusMessage(`Game running • ${event.totalQuestions} questions`);
      setLatestQuestion(null);
    },
    QUESTION: event => {
      const typed = event || {};
      setStatusMessage(`Question ${typed.index ?? "?"}/${state?.total_questions ?? "?"}`);
      setLatestQuestion(typed.payload ?? null);
      setState(prev =>
        prev
          ? {
              ...prev,
              current_question_idx: typed.index ?? prev.current_question_idx,
              started_at: typed.startedAt ?? prev.started_at,
              deadline_at: typed.deadlineAt ?? prev.deadline_at,
            }
          : prev
      );
    },
    LEADERBOARD: event => {
      setLeaderboard(event.top ?? []);
      setYou(event.you ?? null);
    },
    LOBBY_UPDATE: event => {
      const participants = Array.isArray(event.participants) ? event.participants : [];
      setLobby({ participants, pin: event.pin ?? null });
    },
    GAME_ENDED: event => {
      setStatusMessage("Game ended");
      setLeaderboard(event.finalTop ?? []);
    },
  });

  useEffect(() => {
    if (!session) {
      return;
    }
    let cancelled = false;
    api
      .fetchState(session.id)
      .then(nextState => {
        if (cancelled) {
          return;
        }
        setState(nextState);
        setLeaderboard(nextState.leaderboard);
        setYou(nextState.you);
      })
      .catch(err => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load state");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [session, api]);

  const handleCreate = created => {
    setSession(created);
    setLobby({ participants: [], pin: created.pin });
    setStatusMessage("Waiting in lobby");
    setError(null);
  };

  const performAction = async action => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(false);
    }
  };

  const handleStart = () => {
    if (!session) {
      return;
    }
    void performAction(async () => {
      const updated = await api.startSession(session.id);
      setSession(updated);
      setStatusMessage("Game running");
    });
  };

  const handleNext = () => {
    if (!session) {
      return;
    }
    void performAction(async () => {
      await api.advanceSession(session.id);
    });
  };

  const handleEnd = () => {
    if (!session) {
      return;
    }
    void performAction(async () => {
      await api.endSession(session.id);
      setStatusMessage("Game ended");
    });
  };

  if (!session) {
    return createElement(
      "div",
      null,
      createElement("h2", null, "Create a live practice competition"),
      createElement(TeacherLiveSessionForm, {
        classOptions,
        vocabListOptions,
        onCreated: handleCreate,
        api,
      })
    );
  }

  const lobbyList = lobby.participants.length
    ? createElement(
        "ul",
        null,
        lobby.participants.map(name => createElement("li", { key: name }, name))
      )
    : createElement("p", null, "No students joined yet.");

  const questionPreview = latestQuestion
    ? questionRenderer
      ? questionRenderer(latestQuestion)
      : createElement(
          "pre",
          {
            style: {
              background: "#f3f4f6",
              borderRadius: "0.5rem",
              padding: "1rem",
              overflowX: "auto",
            },
          },
          JSON.stringify(latestQuestion, null, 2)
        )
    : createElement("p", null, "Waiting for the first question…");

  const errorNode = error
    ? createElement(
        "p",
        { role: "alert", style: { color: "#b91c1c" } },
        error
      )
    : null;

  return createElement(
    "section",
    {
      "aria-label": "Live session console",
      style: { display: "flex", gap: "1.5rem" },
    },
    createElement(
      "div",
      { style: { flex: 1 } },
      createElement(
        "header",
        { style: { marginBottom: "1rem" } },
        createElement("h2", { style: { marginBottom: "0.25rem" } }, "Session controls"),
        createElement(
          "p",
          { style: { color: "#4b5563" } },
          `PIN ${lobby.pin ?? session.pin} • Status ${session.status}`
        ),
        statusMessage
          ? createElement("p", { style: { color: "#2563eb" } }, statusMessage)
          : null,
        errorNode
      ),
      createElement(
        "div",
        { style: { display: "flex", gap: "0.75rem", marginBottom: "1rem" } },
        createElement(
          "button",
          { type: "button", onClick: handleStart, disabled: busy },
          "Start"
        ),
        createElement(
          "button",
          { type: "button", onClick: handleNext, disabled: busy },
          "Next"
        ),
        createElement(
          "button",
          { type: "button", onClick: handleEnd, disabled: busy },
          "End"
        )
      ),
      createElement(
        "div",
        { "aria-label": "Lobby participants", style: { marginBottom: "1.5rem" } },
        createElement("h3", null, "Lobby"),
        lobbyList
      ),
      createElement(
        "div",
        { "aria-label": "Question preview" },
        createElement("h3", null, "Question preview"),
        questionPreview
      )
    ),
    createElement(MiniLeaderboard, {
      entries: leaderboard,
      you,
      title: "Top students",
    })
  );
}

export default TeacherLiveSessionConsole;
