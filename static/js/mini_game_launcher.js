(function (global) {
  const DEFAULT_TIME_LIMIT = 90000;
  const OVERLAY_ID = "gamehub-mini-game-overlay";
  const STYLE_ID = "gamehub-mini-game-styles";
  let active = null;

  function ensureStyles() {
    if (document.getElementById(STYLE_ID)) {
      return;
    }
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      .gamehub-mini-overlay {
        position: fixed;
        inset: 0;
        background: rgba(15, 23, 42, 0.55);
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 24px;
        z-index: 1050;
        backdrop-filter: blur(2px);
      }
      .gamehub-mini-modal {
        width: 100%;
        max-width: 720px;
        background: #ffffff;
        border-radius: 24px;
        box-shadow: 0 24px 48px rgba(15, 23, 42, 0.35);
        overflow: hidden;
        display: flex;
        flex-direction: column;
        font-family: 'Poppins', sans-serif;
      }
      .gamehub-mini-body {
        padding: 28px;
        display: flex;
        flex-direction: column;
        gap: 20px;
      }
      .gamehub-mini-header {
        display: flex;
        flex-wrap: wrap;
        gap: 16px;
        justify-content: space-between;
        align-items: center;
        border: 1px solid rgba(148, 163, 184, 0.3);
        border-radius: 16px;
        background: #f8fafc;
        padding: 16px 20px;
      }
      .gamehub-mini-header-block {
        display: flex;
        flex-direction: column;
        gap: 4px;
        min-width: 120px;
      }
      .gamehub-mini-header-label {
        font-size: 12px;
        font-weight: 600;
        text-transform: uppercase;
        color: #64748b;
        letter-spacing: 0.05em;
      }
      .gamehub-mini-header-value {
        font-size: 26px;
        font-weight: 700;
        color: #0f172a;
      }
      .gamehub-mini-header-value.positive {
        color: #059669;
      }
      .gamehub-mini-header-value.negative {
        color: #dc2626;
      }
      .gamehub-mini-word {
        display: flex;
        flex-direction: column;
        gap: 12px;
        text-align: center;
      }
      .gamehub-mini-word-prompt {
        font-size: 22px;
        font-weight: 700;
        color: #0f172a;
      }
      .gamehub-mini-word-answer {
        font-size: 16px;
        color: #334155;
      }
      .gamehub-mini-buttons {
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        justify-content: center;
      }
      .gamehub-mini-button {
        flex: 1 1 160px;
        border: none;
        border-radius: 12px;
        padding: 14px 18px;
        font-size: 16px;
        font-weight: 600;
        cursor: pointer;
        color: #ffffff;
        box-shadow: 0 10px 22px rgba(15, 23, 42, 0.15);
        transition: transform 0.15s ease, box-shadow 0.15s ease;
      }
      .gamehub-mini-button.correct {
        background: linear-gradient(90deg, #22c55e 0%, #16a34a 100%);
      }
      .gamehub-mini-button.correct:hover {
        transform: translateY(-1px);
        box-shadow: 0 12px 28px rgba(34, 197, 94, 0.25);
      }
      .gamehub-mini-button.incorrect {
        background: linear-gradient(90deg, #f43f5e 0%, #e11d48 100%);
      }
      .gamehub-mini-button.incorrect:hover {
        transform: translateY(-1px);
        box-shadow: 0 12px 28px rgba(244, 63, 94, 0.25);
      }
      .gamehub-mini-finish {
        align-self: center;
        padding: 10px 18px;
        border-radius: 999px;
        font-size: 14px;
        font-weight: 600;
        color: #0f172a;
        border: 1px solid rgba(148, 163, 184, 0.4);
        background: #ffffff;
        cursor: pointer;
        transition: background 0.15s ease, color 0.15s ease;
      }
      .gamehub-mini-finish:hover {
        background: #0f172a;
        color: #ffffff;
      }
      .gamehub-mini-loading,
      .gamehub-mini-error,
      .gamehub-mini-saving {
        text-align: center;
        display: flex;
        flex-direction: column;
        gap: 12px;
      }
      .gamehub-mini-status-title {
        font-size: 20px;
        font-weight: 700;
        color: #0f172a;
      }
      .gamehub-mini-status-detail {
        font-size: 14px;
        color: #475569;
      }
      .gamehub-mini-close {
        align-self: center;
        padding: 10px 18px;
        border-radius: 999px;
        font-size: 14px;
        font-weight: 600;
        border: none;
        background: #0ea5e9;
        color: #ffffff;
        cursor: pointer;
      }
      @media (max-width: 600px) {
        .gamehub-mini-body {
          padding: 20px;
        }
        .gamehub-mini-button {
          flex: 1 1 100%;
        }
      }
    `;
    document.head.appendChild(style);
  }

  function createOverlay() {
    const existing = document.getElementById(OVERLAY_ID);
    if (existing && existing.parentNode) {
      existing.parentNode.removeChild(existing);
    }
    const backdrop = document.createElement("div");
    backdrop.className = "gamehub-mini-overlay";
    backdrop.id = OVERLAY_ID;

    const modal = document.createElement("div");
    modal.className = "gamehub-mini-modal";

    const body = document.createElement("div");
    body.className = "gamehub-mini-body";

    modal.appendChild(body);
    backdrop.appendChild(modal);

    return { backdrop, modal, body };
  }

  function computeSummary(entries, startedAt) {
    const correct = entries.filter(entry => entry.correct).length;
    const wrong = entries.length - correct;
    const total = entries.length;
    const accuracy = total > 0 ? correct / total : 0;
    const timeMs = Math.max(0, Date.now() - startedAt);

    return {
      score: correct * 10,
      accuracy,
      correct,
      wrong,
      wordsSeen: entries.map(entry => entry.word),
      timeMs,
    };
  }

  function setBodyContent(contentElement) {
    if (!active) return;
    const { body } = active.overlay;
    body.innerHTML = "";
    body.appendChild(contentElement);
  }

  function showLoading(message) {
    const container = document.createElement("div");
    container.className = "gamehub-mini-loading";
    const title = document.createElement("div");
    title.className = "gamehub-mini-status-title";
    title.textContent = message;
    const detail = document.createElement("div");
    detail.className = "gamehub-mini-status-detail";
    detail.textContent = "Fetching your current word set…";
    container.appendChild(title);
    container.appendChild(detail);
    setBodyContent(container);
  }

  function showSaving(summary) {
    const container = document.createElement("div");
    container.className = "gamehub-mini-saving";
    const title = document.createElement("div");
    title.className = "gamehub-mini-status-title";
    title.textContent = "Saving your mini-game results…";
    const detail = document.createElement("div");
    detail.className = "gamehub-mini-status-detail";
    const accuracyPct = Math.round(summary.accuracy * 100);
    detail.textContent = `Score: ${summary.score} • Accuracy: ${accuracyPct}%`;
    container.appendChild(title);
    container.appendChild(detail);
    setBodyContent(container);
  }

  function showError(message, { restoreToken } = {}) {
    if (!active) return;
    active.state = "error";
    const container = document.createElement("div");
    container.className = "gamehub-mini-error";
    const title = document.createElement("div");
    title.className = "gamehub-mini-status-title";
    title.textContent = "Something went wrong";
    const detail = document.createElement("div");
    detail.className = "gamehub-mini-status-detail";
    detail.textContent = message;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "gamehub-mini-close";
    button.textContent = "Close";
    button.addEventListener("click", () => {
      if (restoreToken && global.GameHub && typeof global.GameHub.restoreToken === "function") {
        global.GameHub.restoreToken();
      }
      closeModal();
    });
    container.appendChild(title);
    container.appendChild(detail);
    container.appendChild(button);
    setBodyContent(container);
  }

  function closeModal() {
    if (!active) return;
    if (active.timerId) {
      global.clearInterval(active.timerId);
    }
    if (active.cleanup) {
      try {
        active.cleanup();
      } catch (error) {
        console.error("MiniGame cleanup error", error);
      }
    }
    const overlay = active.overlay;
    const options = active.options;
    if (overlay && overlay.backdrop && overlay.backdrop.parentNode) {
      overlay.backdrop.parentNode.removeChild(overlay.backdrop);
    }
    active = null;
    if (options && typeof options.onClose === "function") {
      try {
        options.onClose();
      } catch (error) {
        console.error("MiniGame onClose error", error);
      }
    }
  }

  function markResult(isCorrect) {
    if (!active || active.state !== "playing") {
      return;
    }
    const words = active.words;
    if (!Array.isArray(words) || words.length === 0) {
      finishGame([]);
      return;
    }
    const currentWord = words[active.index] || null;
    if (!currentWord) {
      finishGame(active.results);
      return;
    }
    active.results.push({ word: currentWord, correct: !!isCorrect });
    updateCounts();
    active.index = (active.index + 1) % words.length;
    renderCurrentWord();

    if (active.results.length >= words.length) {
      global.setTimeout(() => finishGame(active.results.slice()), 0);
    }
  }

  function computeTimeLeftMs() {
    if (!active) return 0;
    const elapsed = Date.now() - active.startedAt;
    const remaining = Math.max(0, active.timeLimitMs - elapsed);
    return remaining;
  }

  function updateTimer() {
    if (!active || active.state !== "playing") {
      return;
    }
    const remaining = computeTimeLeftMs();
    if (active.timeEl) {
      active.timeEl.textContent = `${Math.ceil(remaining / 1000)}s`;
    }
    if (remaining <= 0) {
      finishGame(active.results.slice());
    }
  }

  function updateCounts() {
    if (!active || !Array.isArray(active.results)) {
      return;
    }
    const correct = active.results.filter(entry => entry.correct).length;
    const wrong = active.results.length - correct;
    if (active.correctEl) {
      active.correctEl.textContent = correct;
    }
    if (active.wrongEl) {
      active.wrongEl.textContent = wrong;
    }
  }

  function renderCurrentWord() {
    if (!active) return;
    const words = active.words || [];
    const currentWord = words[active.index] || words[0] || null;
    if (!active.promptEl || !active.answerEl) {
      return;
    }
    if (!currentWord) {
      active.promptEl.textContent = "No words available.";
      active.answerEl.textContent = "";
      active.answerEl.style.display = "none";
      return;
    }
    const prompt = currentWord.prompt || currentWord.question || currentWord.text || "";
    const answer = currentWord.answer || currentWord.translation || "";
    active.promptEl.textContent = prompt || "—";
    if (answer) {
      active.answerEl.textContent = `Target: ${answer}`;
      active.answerEl.style.display = "block";
    } else {
      active.answerEl.textContent = "";
      active.answerEl.style.display = "none";
    }
  }

  function startGame(words) {
    if (!active) return;
    const safeWords = Array.isArray(words) ? words.filter(Boolean) : [];
    active.words = safeWords;
    active.results = [];
    active.index = 0;
    active.startedAt = Date.now();
    active.timeLimitMs = Number.isFinite(active.options.timeLimitMs)
      ? active.options.timeLimitMs
      : DEFAULT_TIME_LIMIT;

    if (safeWords.length === 0) {
      showLoading("No words available right now");
      finishGame([]);
      return;
    }

    active.state = "playing";

    const body = active.overlay.body;
    body.innerHTML = "";

    const header = document.createElement("div");
    header.className = "gamehub-mini-header";

    const timeBlock = document.createElement("div");
    timeBlock.className = "gamehub-mini-header-block";
    const timeLabel = document.createElement("div");
    timeLabel.className = "gamehub-mini-header-label";
    timeLabel.textContent = "Time Left";
    const timeValue = document.createElement("div");
    timeValue.className = "gamehub-mini-header-value";
    timeValue.textContent = `${Math.ceil(active.timeLimitMs / 1000)}s`;
    timeBlock.appendChild(timeLabel);
    timeBlock.appendChild(timeValue);

    const correctBlock = document.createElement("div");
    correctBlock.className = "gamehub-mini-header-block";
    const correctLabel = document.createElement("div");
    correctLabel.className = "gamehub-mini-header-label";
    correctLabel.textContent = "Fed";
    const correctValue = document.createElement("div");
    correctValue.className = "gamehub-mini-header-value positive";
    correctValue.textContent = "0";
    correctBlock.appendChild(correctLabel);
    correctBlock.appendChild(correctValue);

    const wrongBlock = document.createElement("div");
    wrongBlock.className = "gamehub-mini-header-block";
    const wrongLabel = document.createElement("div");
    wrongLabel.className = "gamehub-mini-header-label";
    wrongLabel.textContent = "Missed";
    const wrongValue = document.createElement("div");
    wrongValue.className = "gamehub-mini-header-value negative";
    wrongValue.textContent = "0";
    wrongBlock.appendChild(wrongLabel);
    wrongBlock.appendChild(wrongValue);

    header.appendChild(timeBlock);
    header.appendChild(correctBlock);
    header.appendChild(wrongBlock);

    const wordSection = document.createElement("div");
    wordSection.className = "gamehub-mini-word";
    const promptEl = document.createElement("div");
    promptEl.className = "gamehub-mini-word-prompt";
    const answerEl = document.createElement("div");
    answerEl.className = "gamehub-mini-word-answer";
    wordSection.appendChild(promptEl);
    wordSection.appendChild(answerEl);

    const buttonsRow = document.createElement("div");
    buttonsRow.className = "gamehub-mini-buttons";
    const correctButton = document.createElement("button");
    correctButton.type = "button";
    correctButton.className = "gamehub-mini-button correct";
    correctButton.textContent = "Fed Correctly";
    const wrongButton = document.createElement("button");
    wrongButton.type = "button";
    wrongButton.className = "gamehub-mini-button incorrect";
    wrongButton.textContent = "Missed";
    buttonsRow.appendChild(correctButton);
    buttonsRow.appendChild(wrongButton);

    const finishButton = document.createElement("button");
    finishButton.type = "button";
    finishButton.className = "gamehub-mini-finish";
    finishButton.textContent = "Finish Early";

    body.appendChild(header);
    body.appendChild(wordSection);
    body.appendChild(buttonsRow);
    body.appendChild(finishButton);

    active.timeEl = timeValue;
    active.correctEl = correctValue;
    active.wrongEl = wrongValue;
    active.promptEl = promptEl;
    active.answerEl = answerEl;

    const handleCorrect = () => markResult(true);
    const handleWrong = () => markResult(false);
    const handleFinish = () => finishGame(active.results.slice());

    correctButton.addEventListener("click", handleCorrect);
    wrongButton.addEventListener("click", handleWrong);
    finishButton.addEventListener("click", handleFinish);

    active.cleanup = () => {
      correctButton.removeEventListener("click", handleCorrect);
      wrongButton.removeEventListener("click", handleWrong);
      finishButton.removeEventListener("click", handleFinish);
    };

    renderCurrentWord();
    updateCounts();
    updateTimer();

    active.timerId = global.setInterval(updateTimer, 250);
  }

  function finishGame(forcedEntries) {
    if (!active) return;
    if (active.state === "saving") {
      return;
    }
    if (active.timerId) {
      global.clearInterval(active.timerId);
      active.timerId = null;
    }
    if (active.cleanup) {
      active.cleanup();
      active.cleanup = null;
    }

    const entries = Array.isArray(forcedEntries)
      ? forcedEntries
      : active.results || [];

    const startedAt = active.startedAt || Date.now();
    const summary = computeSummary(entries, startedAt);
    showSaving(summary);
    active.state = "saving";

    const payload = {
      gameKey: "peacock-conveyor",
      mode: active.options.mode || "practice",
      ...summary,
      startedAt,
      endedAt: Date.now(),
    };

    Promise.resolve()
      .then(() => {
        if (active.options.postResult) {
          return active.options.postResult(payload);
        }
        return null;
      })
      .then(() => {
        const streakDelta = summary.accuracy >= 0.9 && summary.correct >= 15 ? 5 : 0;
        const award = {
          pointsDelta: summary.score,
          streakDelta,
          energyDelta: 0,
          tokensDelta: 0,
        };
        if (active.options.awardSession) {
          return Promise.resolve(active.options.awardSession(award, summary)).then(() => award);
        }
        return award;
      })
      .then(award => {
        if (active.options.onSessionAward) {
          try {
            active.options.onSessionAward(award, summary);
          } catch (error) {
            console.error("MiniGame onSessionAward error", error);
          }
        }
        closeModal();
      })
      .catch(error => {
        console.error("MiniGame finalization error", error);
        showError("We couldn't save your mini-game results. Please try again later.", { restoreToken: false });
      });
  }

  function open(options = {}) {
    if (active) {
      return;
    }
    if (!global.GameHub || typeof global.GameHub.consumeToken !== "function") {
      console.warn("MiniGameLauncher requires GameHub");
      return;
    }
    if (!global.GameHub.consumeToken()) {
      return;
    }

    ensureStyles();
    const overlay = createOverlay();
    document.body.appendChild(overlay.backdrop);

    active = {
      options,
      overlay,
      state: "loading",
      timerId: null,
      cleanup: null,
      words: [],
      results: [],
      index: 0,
      startedAt: Date.now(),
      timeLimitMs: Number.isFinite(options.timeLimitMs) ? options.timeLimitMs : DEFAULT_TIME_LIMIT,
      timeEl: null,
      correctEl: null,
      wrongEl: null,
      promptEl: null,
      answerEl: null,
    };

    showLoading("Loading words…");

    Promise.resolve()
      .then(() => {
        if (options.fetchWords) {
          return options.fetchWords(options.mode || "practice");
        }
        return [];
      })
      .then(words => {
        if (!active) {
          return;
        }
        startGame(words);
      })
      .catch(error => {
        console.error("Failed to load mini-game words", error);
        showError("Unable to load your mini-game. Please close and try again.", { restoreToken: true });
      });
  }

  global.MiniGameLauncher = {
    open,
  };
})(typeof window !== "undefined" ? window : globalThis);
