import "@testing-library/jest-dom";
import React from "react";
import { jest } from "@jest/globals";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import StudentLiveGameView from "../StudentLiveGameView";

const initialState = {
  session_id: "session-1",
  status: "RUNNING",
  current_question_idx: 1,
  total_questions: 5,
  question_time_sec: 20,
  started_at: new Date().toISOString(),
  deadline_at: new Date().toISOString(),
  leaderboard: [
    { rank: 1, name: "Avery", score: 1200, streak: 2 },
    { rank: 2, name: "Blair", score: 900, streak: 1 },
  ],
  you: { rank: 3, score: 800, streak: 0 },
};

const sampleQuestion = {
  prompt: "Translate ‘hola’",
};

describe("StudentLiveGameView", () => {
  it("joins the session and submits an answer", async () => {
    const joinSession = jest.fn().mockResolvedValue(initialState);
    const fetchState = jest.fn().mockResolvedValue(initialState);
    const submitAnswer = jest.fn().mockResolvedValue({
      accepted: true,
      isCorrect: true,
      scoreDelta: 140,
    });

    render(
      React.createElement(StudentLiveGameView, {
        sessionId: "session-1",
        initialQuestionPayload: sampleQuestion,
        api: {
          createSession: jest.fn(),
          startSession: jest.fn(),
          advanceSession: jest.fn(),
          endSession: jest.fn(),
          joinSession,
          fetchState,
          submitAnswer,
        },
        renderQuestion: (payload, onSubmit) =>
          React.createElement(
            "button",
            { type: "button", onClick: () => onSubmit("hola") },
            `Answer ${payload.prompt}`
          ),
      })
    );

    fireEvent.click(screen.getByRole("button", { name: /join session/i }));

    await waitFor(() => expect(joinSession).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: /Answer/ }));

    await waitFor(() => expect(submitAnswer).toHaveBeenCalledWith("session-1", {
      questionIndex: 1,
      answerPayload: "hola",
    }));
  });

  it("shows errors when join fails", async () => {
    const joinSession = jest.fn().mockRejectedValue(new Error("nope"));

    render(
      React.createElement(StudentLiveGameView, {
        sessionId: "session-2",
        api: {
          createSession: jest.fn(),
          startSession: jest.fn(),
          advanceSession: jest.fn(),
          endSession: jest.fn(),
          joinSession,
          fetchState: jest.fn(),
          submitAnswer: jest.fn(),
        },
      })
    );

    fireEvent.click(screen.getByRole("button", { name: /join session/i }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("nope"));
  });
});
