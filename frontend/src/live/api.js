const JSON_HEADERS = {
  "Content-Type": "application/json",
  Accept: "application/json",
};

function handleError(response, data) {
  const detail = data && typeof data === "object" ? data.detail : null;
  const message = detail || `Request failed with status ${response.status}`;
  throw new Error(message);
}

async function handleJsonResponse(response) {
  const contentType = response.headers.get("content-type") || "";
  const isJson = contentType.includes("application/json");
  const data = isJson ? await response.json() : null;
  if (!response.ok) {
    handleError(response, data);
  }
  return (data ?? {});
}

function buildUrl(path) {
  if (path.startsWith("http")) {
    return path;
  }
  return `/api/live-games${path}`;
}

export function createLiveApi(fetchImpl = fetch) {
  return {
    async createSession(payload) {
      const response = await fetchImpl(buildUrl("/"), {
        method: "POST",
        headers: JSON_HEADERS,
        credentials: "include",
        body: JSON.stringify({
          class_id: payload.classId,
          vocab_list_ids: payload.vocabListIds,
          total_questions: payload.totalQuestions,
          question_time_sec: payload.questionTimeSec,
          scoring_mode: payload.scoringMode,
        }),
      });
      return handleJsonResponse(response);
    },

    async startSession(sessionId) {
      const response = await fetchImpl(buildUrl(`/${sessionId}/start/`), {
        method: "POST",
        headers: JSON_HEADERS,
        credentials: "include",
      });
      return handleJsonResponse(response);
    },

    async advanceSession(sessionId) {
      const response = await fetchImpl(buildUrl(`/${sessionId}/next/`), {
        method: "POST",
        headers: JSON_HEADERS,
        credentials: "include",
      });
      return handleJsonResponse(response);
    },

    async endSession(sessionId) {
      const response = await fetchImpl(buildUrl(`/${sessionId}/end/`), {
        method: "POST",
        headers: JSON_HEADERS,
        credentials: "include",
      });
      if (!response.ok) {
        await handleJsonResponse(response);
      }
    },

    async joinSession(sessionId, payload = {}) {
      const response = await fetchImpl(buildUrl(`/${sessionId}/join/`), {
        method: "POST",
        headers: JSON_HEADERS,
        credentials: "include",
        body: JSON.stringify(payload),
      });
      return handleJsonResponse(response);
    },

    async submitAnswer(sessionId, payload) {
      const response = await fetchImpl(buildUrl(`/${sessionId}/answer/`), {
        method: "POST",
        headers: JSON_HEADERS,
        credentials: "include",
        body: JSON.stringify({
          questionIndex: payload.questionIndex,
          answerPayload: payload.answerPayload,
        }),
      });
      return handleJsonResponse(response);
    },

    async fetchState(sessionId) {
      const response = await fetchImpl(buildUrl(`/${sessionId}/state/`), {
        method: "GET",
        headers: JSON_HEADERS,
        credentials: "include",
      });
      return handleJsonResponse(response);
    },
  };
}

export default createLiveApi;
