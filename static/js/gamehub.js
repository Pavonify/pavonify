(function (global) {
  const KEY = "pavonify_gamehub_v1";
  const MAX_TOKENS = 3;
  const listeners = new Set();
  const state = {
    energy: 0,
    tokens: 0,
    maxTokens: MAX_TOKENS,
  };

  function clampEnergy(value) {
    if (!Number.isFinite(value)) return 0;
    return Math.min(100, Math.max(0, Math.round(value)));
  }

  function clampTokens(value) {
    if (!Number.isFinite(value)) return 0;
    return Math.min(state.maxTokens, Math.max(0, Math.round(value)));
  }

  function loadState() {
    try {
      const raw = global.localStorage ? global.localStorage.getItem(KEY) : null;
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (typeof parsed.energy === "number") {
        state.energy = clampEnergy(parsed.energy);
      }
      if (typeof parsed.tokens === "number") {
        state.tokens = clampTokens(parsed.tokens);
      }
    } catch (error) {
      console.warn("GameHub: failed to load state", error);
    }
  }

  function persistState() {
    try {
      if (!global.localStorage) return;
      global.localStorage.setItem(
        KEY,
        JSON.stringify({ energy: state.energy, tokens: state.tokens })
      );
    } catch (error) {
      console.warn("GameHub: failed to persist state", error);
    }
  }

  function notify() {
    const snapshot = getState();
    listeners.forEach(listener => {
      try {
        listener(snapshot);
      } catch (error) {
        console.error("GameHub listener error", error);
      }
    });
  }

  function getState() {
    return {
      energy: state.energy,
      tokens: state.tokens,
      maxTokens: state.maxTokens,
    };
  }

  function setEnergy(value) {
    state.energy = clampEnergy(value);
    persistState();
    notify();
  }

  function resetEnergy() {
    setEnergy(0);
  }

  function setTokens(value) {
    state.tokens = clampTokens(value);
    persistState();
    notify();
  }

  function gainEnergy(base, streak) {
    const safeBase = Number.isFinite(base) ? Math.max(0, Math.round(base)) : 0;
    const safeStreak = Number.isFinite(streak) ? streak : 0;
    const bonus = safeStreak >= 20 ? 2 : safeStreak >= 10 ? 1 : 0;
    let nextEnergy = state.energy + safeBase + bonus;
    let nextTokens = state.tokens;

    while (nextEnergy >= 100 && nextTokens < state.maxTokens) {
      nextEnergy -= 100;
      nextTokens += 1;
    }

    if (nextTokens >= state.maxTokens) {
      nextEnergy = Math.min(nextEnergy, 99);
    }

    state.energy = clampEnergy(nextEnergy);
    state.tokens = clampTokens(nextTokens);
    persistState();
    notify();
  }

  function consumeToken() {
    if (state.tokens <= 0) {
      return false;
    }
    state.tokens = clampTokens(state.tokens - 1);
    persistState();
    notify();
    return true;
  }

  function restoreToken() {
    if (state.tokens >= state.maxTokens) {
      return false;
    }
    state.tokens = clampTokens(state.tokens + 1);
    persistState();
    notify();
    return true;
  }

  function subscribe(listener) {
    if (typeof listener !== "function") {
      return function unsubscribe() {};
    }
    listeners.add(listener);
    try {
      listener(getState());
    } catch (error) {
      console.error("GameHub listener error", error);
    }
    return function unsubscribe() {
      listeners.delete(listener);
    };
  }

  function ensureEnergyStyles() {
    if (document.getElementById("gamehub-energy-styles")) {
      return;
    }
    const style = document.createElement("style");
    style.id = "gamehub-energy-styles";
    style.textContent = `
      .gamehub-energy-container {
        display: inline-flex;
        align-items: center;
        gap: 12px;
      }
      .gamehub-energy-bar {
        position: relative;
        width: 160px;
        height: 20px;
        border-radius: 9999px;
        background: #e0f2fe;
        overflow: hidden;
        box-shadow: inset 0 0 0 1px rgba(14, 116, 144, 0.12);
      }
      .gamehub-energy-fill {
        position: absolute;
        left: 0;
        top: 0;
        bottom: 0;
        width: 0;
        background: linear-gradient(90deg, #38bdf8 0%, #0ea5e9 100%);
        transition: width 0.3s ease;
      }
      .gamehub-energy-label {
        position: absolute;
        inset: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 12px;
        font-weight: 600;
        color: #0f172a;
        text-shadow: 0 1px 2px rgba(255, 255, 255, 0.6);
        pointer-events: none;
      }
      .gamehub-energy-button {
        border: none;
        border-radius: 9999px;
        padding: 6px 14px;
        font-size: 14px;
        font-weight: 600;
        background: #e5e7eb;
        color: #6b7280;
        cursor: not-allowed;
        transition: transform 0.2s ease, background-color 0.2s ease, color 0.2s ease;
        box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.25);
      }
      .gamehub-energy-button.is-active {
        background: linear-gradient(90deg, #10b981 0%, #059669 100%);
        color: #ffffff;
        cursor: pointer;
        box-shadow: 0 10px 20px rgba(16, 185, 129, 0.25);
      }
      .gamehub-energy-button.is-active:hover {
        transform: scale(1.05);
      }
      .gamehub-energy-button:focus {
        outline: none;
        box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.35);
      }
    `;
    document.head.appendChild(style);
  }

  function renderEnergyMeter(container, options = {}) {
    if (!container) {
      return function noop() {};
    }
    ensureEnergyStyles();
    container.innerHTML = "";

    const wrapper = document.createElement("div");
    wrapper.className = "gamehub-energy-container";

    const bar = document.createElement("div");
    bar.className = "gamehub-energy-bar";
    const fill = document.createElement("div");
    fill.className = "gamehub-energy-fill";
    const label = document.createElement("div");
    label.className = "gamehub-energy-label";
    label.textContent = "0% Energy";

    bar.appendChild(fill);
    bar.appendChild(label);

    const button = document.createElement("button");
    button.type = "button";
    button.className = "gamehub-energy-button";
    button.textContent = `🎮 x0/${state.maxTokens}`;
    button.disabled = true;

    wrapper.appendChild(bar);
    wrapper.appendChild(button);
    container.appendChild(wrapper);

    const onLaunch = typeof options.onLaunch === "function" ? options.onLaunch : null;

    function update(snapshot) {
      const pct = clampEnergy(snapshot.energy);
      fill.style.width = `${pct}%`;
      label.textContent = `${pct}% Energy`;
      button.textContent = `🎮 x${snapshot.tokens}/${snapshot.maxTokens}`;
      button.disabled = snapshot.tokens <= 0;
      if (snapshot.tokens > 0) {
        button.classList.add("is-active");
      } else {
        button.classList.remove("is-active");
      }
    }

    const unsubscribe = subscribe(update);

    function handleClick() {
      if (button.disabled) {
        return;
      }
      if (onLaunch) {
        onLaunch();
      }
    }

    button.addEventListener("click", handleClick);

    return function destroy() {
      unsubscribe();
      button.removeEventListener("click", handleClick);
      if (container.contains(wrapper)) {
        container.removeChild(wrapper);
      }
    };
  }

  loadState();

  global.GameHub = {
    getState,
    subscribe,
    gainEnergy,
    consumeToken,
    restoreToken,
    resetEnergy,
    setEnergy,
    renderEnergyMeter,
  };
})(typeof window !== "undefined" ? window : globalThis);
