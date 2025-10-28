import React, { useMemo, useState } from "react";

import { createLiveApi } from "../api";

const { createElement } = React;

export function TeacherLiveSessionForm({
  classOptions = [],
  vocabListOptions = [],
  onCreated,
  api = createLiveApi(),
}) {
  const [formState, setFormState] = useState({
    classId: classOptions[0]?.id ?? "",
    vocabListIds: vocabListOptions.length ? [vocabListOptions[0]?.id ?? ""] : [],
    totalQuestions: 10,
    questionTimeSec: 20,
    scoringMode: "STANDARD",
  });
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const scoringModes = useMemo(
    () => [
      { id: "STANDARD", label: "Standard" },
      { id: "FAST", label: "Fast" },
      { id: "STREAKY", label: "Streaky" },
    ],
    []
  );

  const handleChange = (key, value) => {
    setFormState(prev => ({
      ...prev,
      [key]: value,
    }));
  };

  const handleSubmit = async event => {
    event.preventDefault();
    if (!formState.classId) {
      setError("Select a class to continue.");
      return;
    }
    if (!formState.vocabListIds.length) {
      setError("Select at least one vocabulary list.");
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      const session = await api.createSession(formState);
      if (onCreated) {
        onCreated(session);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create session");
    } finally {
      setSubmitting(false);
    }
  };

  const classSelect = createElement(
    "select",
    {
      id: "live-class",
      value: formState.classId,
      onChange: event => handleChange("classId", event.target.value),
    },
    classOptions.map(option =>
      createElement(
        "option",
        { key: option.id, value: option.id },
        option.label
      )
    )
  );

  const vocabSelect = createElement(
    "select",
    {
      id: "live-vocab-lists",
      multiple: true,
      value: formState.vocabListIds.map(String),
      onChange: event => {
        const { options } = event.target;
        const selected = [];
        for (let index = 0; index < options.length; index += 1) {
          const option = options[index];
          if (option.selected) {
            selected.push(option.value);
          }
        }
        handleChange("vocabListIds", selected);
      },
    },
    vocabListOptions.map(option =>
      createElement(
        "option",
        { key: option.id, value: option.id },
        option.label
      )
    )
  );

  const totalInput = createElement("input", {
    id: "live-total-questions",
    type: "number",
    min: 1,
    value: formState.totalQuestions,
    onChange: event => handleChange("totalQuestions", Number(event.target.value)),
  });

  const timeInput = createElement("input", {
    id: "live-question-time",
    type: "number",
    min: 5,
    value: formState.questionTimeSec,
    onChange: event => handleChange("questionTimeSec", Number(event.target.value)),
  });

  const scoringSelect = createElement(
    "select",
    {
      id: "live-scoring-mode",
      value: formState.scoringMode,
      onChange: event => handleChange("scoringMode", event.target.value),
    },
    scoringModes.map(mode =>
      createElement(
        "option",
        { key: mode.id, value: mode.id },
        mode.label
      )
    )
  );

  const errorNode = error
    ? createElement(
        "p",
        { role: "alert", style: { color: "#b91c1c" } },
        error
      )
    : null;

  return createElement(
    "form",
    { onSubmit: handleSubmit, "aria-label": "Create live practice session" },
    createElement(
      "div",
      { className: "form-field" },
      createElement("label", { htmlFor: "live-class" }, "Class"),
      classSelect
    ),
    createElement(
      "div",
      { className: "form-field" },
      createElement("label", { htmlFor: "live-vocab-lists" }, "Vocabulary lists"),
      vocabSelect
    ),
    createElement(
      "div",
      { className: "form-field" },
      createElement("label", { htmlFor: "live-total-questions" }, "Total questions"),
      totalInput
    ),
    createElement(
      "div",
      { className: "form-field" },
      createElement("label", { htmlFor: "live-question-time" }, "Seconds per question"),
      timeInput
    ),
    createElement(
      "div",
      { className: "form-field" },
      createElement("label", { htmlFor: "live-scoring-mode" }, "Scoring mode"),
      scoringSelect
    ),
    errorNode,
    createElement(
      "button",
      { type: "submit", disabled: submitting },
      submitting ? "Creating…" : "Create live game"
    )
  );
}

export default TeacherLiveSessionForm;
