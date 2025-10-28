import React, { useEffect, useMemo, useState } from "react";

import { createLiveApi } from "../api";
import { useLiveGameSocket } from "../hooks/useLiveGameSocket";

import MiniLeaderboard from "./MiniLeaderboard";

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

function FallbackQuestion({ payload, onSubmit, context }) {
  const [answer, setAnswer] = useState("");

  return createElement(
    "div",
    { style: { display: "grid", gap: "0.75rem" } },
    createElement(
      "p",
      null,
      typeof payload.prompt === "string" ? payload.prompt : "Answer the question"
    ),
    createElement("input", {
      "aria-label": "Answer",
      type: "text",
      value: answer,
      onChange: event => setAnswer(event.target.value),
      disabled: context.locked,
    }),
    createElement(
      "button",
      { type: "button", onClick: () => onSubmit(answer), disabled: context.locked },
      "Submit"
    ),
    context.deadlineAt
      ? createElement(
          "small",
          null,
          `Deadline: ${new Date(context.deadlineAt).toLocaleTimeString()}`
        )
      : null
  );
}

const fallbackRenderer = (payload, onSubmit, context) =>
  createElement(FallbackQuestion, { payload, onSubmit, context });

export function StudentLiveGameView({
  sessionId,
  api = createLiveApi(),
  wsBaseUrl,
  renderQuestion = fallbackRenderer,
  onAnswerAccepted,
  initialQuestionPayload,
}) {
  const [state, setState] = useState(null);
  const [questionState, setQuestionState] = useState({
    payload: initialQuestionPayload ?? null,
    deadlineAt: null,
    locked: false,
  });
  const [leaderboard, setLeaderboard] = useState(state?.leaderboard ?? []);
  const [you, setYou] = useState(state?.you ?? null);
  const [joining, setJoining] = useState(false);
  const [joined, setJoined] = useState(false);
  const [error, setError] = useState(null);
  const [submissionError, setSubmissionError] = useState(null);

  const wsUrl = useMemo(
    () => buildWsUrl(wsBaseUrl, `/ws/live-games/${sessionId}/`),
    [sessionId, wsBaseUrl]
  );

  useLiveGameSocket(wsUrl, {
    QUESTION: event => {
      const typed = event || {};
      setQuestionState({
        payload: typed.payload ?? null,
        deadlineAt: typed.deadlineAt ?? null,
        locked: false,
      });
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
    GAME_ENDED: () => {
      setQuestionState(prev => ({ ...prev, locked: true }));
    },
  });

  useEffect(() => {
    if (!joined) {
      return;
    }
    let cancelled = false;
    api
      .fetchState(sessionId)
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
  }, [joined, sessionId, api]);

  const joinSession = () => {
    setJoining(true);
    setError(null);
    api
      .joinSession(sessionId)
      .then(nextState => {
        setJoined(true);
        setState(nextState);
        setLeaderboard(nextState.leaderboard);
        setYou(nextState.you);
      })
      .catch(err => {
        setError(err instanceof Error ? err.message : "Unable to join session");
      })
      .finally(() => {
        setJoining(false);
      });
  };

  const handleSubmit = async answerPayload => {
    if (!state) {
      return;
    }
    setSubmissionError(null);
    setQuestionState(prev => ({ ...prev, locked: true }));
    try {
      const response = await api.submitAnswer(sessionId, {
        questionIndex: state.current_question_idx,
        answerPayload,
      });
      if (onAnswerAccepted) {
        onAnswerAccepted(response);
      }
    } catch (err) {
      setSubmissionError(err instanceof Error ? err.message : "Failed to submit answer");
      setQuestionState(prev => ({ ...prev, locked: false }));
    }
  };

  if (!joined) {
    return createElement(
      "section",
      { "aria-label": "Join live practice" },
      createElement("h2", null, "Live competition"),
      error
        ? createElement(
            "p",
            { role: "alert", style: { color: "#b91c1c" } },
            error
          )
        : null,
      createElement(
        "button",
        { type: "button", onClick: joinSession, disabled: joining },
        joining ? "Joining…" : "Join session"
      )
    );
  }

  const questionContent = questionState.payload
    ? createElement(
        "div",
        null,
        renderQuestion(questionState.payload, handleSubmit, {
          deadlineAt: questionState.deadlineAt,
          locked: questionState.locked,
        })
      )
    : createElement("p", null, "Waiting for the host to start…");

  const submissionErrorNode = submissionError
    ? createElement(
        "p",
        { role: "alert", style: { color: "#b91c1c", marginTop: "0.75rem" } },
        submissionError
      )
    : null;

  const deadlineInfo = state?.deadline_at
    ? createElement(
        "p",
        { style: { color: "#6b7280" } },
        `Ends at ${new Date(state.deadline_at).toLocaleTimeString()}`
      )
    : null;

  return createElement(
    "section",
    {
      "aria-label": "Live practice experience",
      style: { display: "flex", gap: "1.5rem", alignItems: "flex-start" },
    },
    createElement(
      "div",
      { style: { flex: 1 } },
      createElement(
        "header",
        { style: { marginBottom: "1rem" } },
        createElement("h2", null, `Question ${state?.current_question_idx ?? 0}`),
        deadlineInfo
      ),
      questionContent,
      submissionErrorNode
    ),
    createElement(MiniLeaderboard, { entries: leaderboard, you })
  );
}

export default StudentLiveGameView;
