import "@testing-library/jest-dom";
import React from "react";
import { jest } from "@jest/globals";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import TeacherLiveSessionForm from "../TeacherLiveSessionForm";

const classOptions = [
  { id: "class-1", label: "Spanish A" },
  { id: "class-2", label: "French B" },
];

const vocabOptions = [
  { id: "list-1", label: "Unit 1" },
  { id: "list-2", label: "Unit 2" },
];

describe("TeacherLiveSessionForm", () => {
  it("submits the creation payload", async () => {
    const createSession = jest.fn().mockResolvedValue({
      id: "session-1",
      pin: "123456",
      status: "LOBBY",
      total_questions: 10,
      question_time_sec: 20,
      scoring_mode: "STANDARD",
      clazz: "class-1",
    });

    const onCreated = jest.fn();

    render(
      React.createElement(TeacherLiveSessionForm, {
        classOptions,
        vocabListOptions: vocabOptions,
        onCreated,
        api: {
          createSession,
          startSession: jest.fn(),
          advanceSession: jest.fn(),
          endSession: jest.fn(),
          joinSession: jest.fn(),
          submitAnswer: jest.fn(),
          fetchState: jest.fn(),
        },
      })
    );

    fireEvent.change(screen.getByLabelText(/Class/i), {
      target: { value: "class-2" },
    });

    const listSelect = screen.getByLabelText(/Vocabulary lists/i);
    Array.from(listSelect.options).forEach(option => {
      // eslint-disable-next-line no-param-reassign -- test helper to mark selected options
      option.selected = option.value === "list-1" || option.value === "list-2";
    });
    fireEvent.change(listSelect);

    fireEvent.change(screen.getByLabelText(/Total questions/i), {
      target: { value: "12" },
    });

    fireEvent.change(screen.getByLabelText(/Seconds per question/i), {
      target: { value: "25" },
    });

    fireEvent.change(screen.getByLabelText(/Scoring mode/i), {
      target: { value: "FAST" },
    });

    fireEvent.click(screen.getByRole("button", { name: /create live game/i }));

    await waitFor(() => expect(createSession).toHaveBeenCalledTimes(1));

    expect(createSession).toHaveBeenCalledWith({
      classId: "class-2",
      vocabListIds: ["list-1", "list-2"],
      totalQuestions: 12,
      questionTimeSec: 25,
      scoringMode: "FAST",
    });

    expect(onCreated).toHaveBeenCalledWith(
      expect.objectContaining({ id: "session-1", pin: "123456" })
    );
  });

  it("shows validation errors", async () => {
    render(
      React.createElement(TeacherLiveSessionForm, {
        classOptions: [],
        vocabListOptions: [],
        api: {
          createSession: jest.fn(),
          startSession: jest.fn(),
          advanceSession: jest.fn(),
          endSession: jest.fn(),
          joinSession: jest.fn(),
          submitAnswer: jest.fn(),
          fetchState: jest.fn(),
        },
      })
    );

    fireEvent.click(screen.getByRole("button", { name: /create live game/i }));

    expect(screen.getByRole("alert")).toHaveTextContent(/Select a class/i);
  });
});
