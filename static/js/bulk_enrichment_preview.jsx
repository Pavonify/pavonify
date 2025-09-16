const { useEffect, useState, useCallback } = React;

function getCookie(name) {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

function toPlainText(value) {
  if (!value) {
    return "";
  }
  return value.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
}

function BulkAddEnrichmentPreview({ words, listId, onClose, fetchImpl }) {
  const fetchFn = fetchImpl || fetch;
  const [rows, setRows] = useState([]);
  const [selectedImage, setSelectedImage] = useState({});
  const [approveImage, setApproveImage] = useState({});
  const [factEdits, setFactEdits] = useState({});
  const [approveFact, setApproveFact] = useState({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [refreshingWord, setRefreshingWord] = useState(null);

  const fetchPreviewFor = useCallback(async (targetWords) => {
    if (!targetWords || !targetWords.length) {
      return [];
    }

    const headers = { "Content-Type": "application/json" };
    const csrfToken = getCookie("csrftoken");
    if (csrfToken) {
      headers["X-CSRFToken"] = csrfToken;
    }

    const response = await fetchFn("/api/vocab/enrichment/preview", {
      method: "POST",
      headers,
      credentials: "include",
      body: JSON.stringify({ words: targetWords }),
    });

    let data = null;
    try {
      data = await response.json();
    } catch (err) {
      if (!response.ok) {
        throw new Error("Failed to load preview");
      }
      throw err;
    }

    if (!response.ok) {
      const detail = data && typeof data === "object" && data.detail ? data.detail : null;
      throw new Error(detail || "Failed to load preview");
    }

    if (!Array.isArray(data)) {
      throw new Error("Unexpected response from server");
    }

    return data;
  }, [fetchFn]);

  const applyInitialRows = useCallback((rowsData) => {
    const initSel = {};
    const initFact = {};

    rowsData.forEach((item) => {
      initSel[item.word] = (item.images && item.images[0]) || null;
      initFact[item.word] = Object.assign({}, item.fact || {});
    });

    setRows(rowsData);
    setSelectedImage(initSel);
    setFactEdits(initFact);
    setApproveImage({});
    setApproveFact({});
  }, []);

  const replaceRow = useCallback((word, updatedRow) => {
    const cleanedWord = (word || "").trim();
    const nextRow = Object.assign({}, updatedRow, {
      word: cleanedWord,
      images: Array.isArray(updatedRow.images) ? updatedRow.images : [],
    });
    const candidates = nextRow.images;

    setRows((prev) => {
      const exists = prev.some((r) => r.word === cleanedWord);
      if (!exists) {
        return prev.concat(nextRow);
      }
      return prev.map((r) => (r.word === cleanedWord ? nextRow : r));
    });

    setSelectedImage((prev) => {
      const next = Object.assign({}, prev);
      const previousChoice = prev[cleanedWord];
      const match = candidates.find((img) => previousChoice && previousChoice.url === img.url) || candidates[0] || null;
      next[cleanedWord] = match;
      return next;
    });

    setFactEdits((prev) => Object.assign({}, prev, { [cleanedWord]: Object.assign({}, nextRow.fact || {}) }));
    setApproveImage((prev) => Object.assign({}, prev, { [cleanedWord]: false }));
    setApproveFact((prev) => Object.assign({}, prev, { [cleanedWord]: false }));
  }, []);

  useEffect(() => {
    let active = true;

    (async () => {
      try {
        setError(null);
        setLoading(true);
        const rowsData = await fetchPreviewFor(words);
        if (!active) {
          return;
        }
        applyInitialRows(rowsData);
      } catch (err) {
        if (!active) {
          return;
        }
        setRows([]);
        setSelectedImage({});
        setFactEdits({});
        setApproveImage({});
        setApproveFact({});
        setError(err && err.message ? err.message : "Failed to load preview");
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    })();

    return () => {
      active = false;
    };
  }, [words, fetchPreviewFor, applyInitialRows]);

  const refreshWord = async (word) => {
    if (!word) {
      return;
    }

    try {
      setError(null);
      setRefreshingWord(word);
      const rowsData = await fetchPreviewFor([word]);
      const normalized = word.trim().toLowerCase();
      const updatedRow = rowsData.find((item) => (item.word || "").trim().toLowerCase() === normalized) || rowsData[0] || null;
      if (!updatedRow) {
        throw new Error("No enrichment suggestions returned.");
      }
      replaceRow(word, updatedRow);
    } catch (err) {
      setError(err && err.message ? err.message : "Failed to refresh suggestions");
    } finally {
      setRefreshingWord(null);
    }
  };

  const reloadAll = async () => {
    if (!words || !words.length) {
      return;
    }

    try {
      setError(null);
      setLoading(true);
      const rowsData = await fetchPreviewFor(words);
      applyInitialRows(rowsData);
    } catch (err) {
      setError(err && err.message ? err.message : "Failed to refresh suggestions");
    } finally {
      setLoading(false);
    }
  };

  const resetFactToSuggestion = (word) => {
    const row = rows.find((item) => item.word === word);
    if (!row) {
      return;
    }
    setFactEdits((prev) => Object.assign({}, prev, { [word]: Object.assign({}, row.fact || {}) }));
    setApproveFact((prev) => Object.assign({}, prev, { [word]: false }));
  };

  const clearImageSelection = (word) => {
    setSelectedImage((prev) => Object.assign({}, prev, { [word]: null }));
    setApproveImage((prev) => Object.assign({}, prev, { [word]: false }));
  };

  const onConfirm = async () => {
    try {
      setSaving(true);
      setError(null);
      const items = rows.map((r) => {
        const image = selectedImage[r.word];
        const fact = factEdits[r.word];
        const factText = (fact && fact.text) || "";
        return {
          word: r.word,
          image,
          fact,
          approveImage: Boolean(approveImage[r.word] && image),
          approveFact: Boolean(approveFact[r.word] && factText.trim()),
        };
      });
      const headers = { "Content-Type": "application/json" };
      const csrfToken = getCookie("csrftoken");
      if (csrfToken) {
        headers["X-CSRFToken"] = csrfToken;
      }
      const res = await fetchFn("/api/vocab/enrichment/confirm", {
        method: "POST",
        headers,
        credentials: "include",
        body: JSON.stringify({ list_id: listId, items }),
      });
      if (!res.ok) {
        throw new Error("Save failed");
      }
      onClose();
    } catch (err) {
      setError(err && err.message ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="enrichment-loading">Loading enrichments…</div>;
  }

  const disableGlobalActions = Boolean(refreshingWord) || saving;

  return (
    <div className="enrichment-preview">
      <div className="enrichment-toolbar">
        <div>
          <h2>Preview Enrichments</h2>
          <p>Pick the best match for each word, then approve the items you want to add.</p>
        </div>
        <button
          type="button"
          className="enrichment-button enrichment-button--ghost"
          onClick={reloadAll}
          disabled={disableGlobalActions}
        >
          Refresh all suggestions
        </button>
      </div>

      {error && (
        <div className="enrichment-alert" role="alert">
          <div>{error}</div>
          <button
            type="button"
            className="enrichment-button enrichment-button--text"
            onClick={reloadAll}
            disabled={disableGlobalActions}
          >
            Try again
          </button>
        </div>
      )}

      {rows.length === 0 ? (
        <div className="enrichment-empty-state">No enrichment suggestions were generated for these words.</div>
      ) : (
        rows.map((row) => {
          const currentImage = selectedImage[row.word] || null;
          const factState = factEdits[row.word] || {};
          const factValue = factState.text || "";
          const factType = factState.type || (row.fact && row.fact.type) || "trivia";
          const factConfidence =
            typeof factState.confidence === "number"
              ? factState.confidence
              : row.fact && typeof row.fact.confidence === "number"
              ? row.fact.confidence
              : null;
          const confidenceLabel =
            typeof factConfidence === "number" && !Number.isNaN(factConfidence)
              ? `${Math.round(Math.max(0, Math.min(1, factConfidence)) * 100)}% confidence`
              : null;
          const canApproveFact = factValue.trim().length > 0;
          const isRefreshing = refreshingWord === row.word;

          return (
            <section key={row.word} className="enrichment-card">
              <div className="enrichment-card-header">
                <h3 className="enrichment-card-title">{row.word}</h3>
                <div className="enrichment-card-actions">
                  <button
                    type="button"
                    className="enrichment-button enrichment-button--ghost"
                    onClick={() => refreshWord(row.word)}
                    disabled={isRefreshing || disableGlobalActions}
                  >
                    {isRefreshing ? "Refreshing…" : "New suggestions"}
                  </button>
                  <button
                    type="button"
                    className="enrichment-button enrichment-button--text"
                    onClick={() => resetFactToSuggestion(row.word)}
                    disabled={isRefreshing}
                  >
                    Reset fact text
                  </button>
                </div>
              </div>

              <div className="enrichment-grid">
                <div className="enrichment-images">
                  <span className="enrichment-label">Images</span>
                  {currentImage ? (
                    <div className="enrichment-selected-image">
                      <img src={currentImage.thumb || currentImage.url} alt={row.word} />
                      <div className="enrichment-image-meta">
                        <div>
                          <strong>{currentImage.source || "Wikimedia"}</strong>
                          {currentImage.license ? ` • ${currentImage.license}` : ""}
                        </div>
                        {currentImage.attribution && <div>{toPlainText(currentImage.attribution)}</div>}
                      </div>
                    </div>
                  ) : (
                    <div className="enrichment-empty">No images yet. Try refreshing to search again.</div>
                  )}

                  {row.images && row.images.length > 0 && (
                    <div className="enrichment-thumb-list">
                      {row.images.map((img) => {
                        const selected = currentImage && currentImage.url === img.url;
                        return (
                          <button
                            type="button"
                            key={img.url}
                            className={`enrichment-thumb${selected ? " is-selected" : ""}`}
                            onClick={() =>
                              setSelectedImage((prev) => Object.assign({}, prev, { [row.word]: img }))
                            }
                            title={toPlainText(img.attribution)}
                          >
                            <img src={img.thumb || img.url} alt={row.word} />
                          </button>
                        );
                      })}
                    </div>
                  )}

                  <div className="enrichment-card-actions">
                    <label className="enrichment-checkbox">
                      <input
                        type="checkbox"
                        checked={Boolean(approveImage[row.word]) && Boolean(currentImage)}
                        onChange={(event) =>
                          setApproveImage((prev) =>
                            Object.assign({}, prev, { [row.word]: event.target.checked })
                          )
                        }
                        disabled={!currentImage}
                      />
                      Approve selected image
                    </label>
                    <button
                      type="button"
                      className="enrichment-button enrichment-button--text"
                      onClick={() => clearImageSelection(row.word)}
                      disabled={!currentImage}
                    >
                      Remove image
                    </button>
                  </div>
                </div>

                <div className="enrichment-fact">
                  <span className="enrichment-label">Word fact</span>
                  <div className="enrichment-fact-meta">
                    <span className="enrichment-badge" data-type={factType}>
                      {factType}
                    </span>
                    {confidenceLabel && <span>{confidenceLabel}</span>}
                  </div>
                  <textarea
                    className="enrichment-fact-text"
                    maxLength={220}
                    value={factValue}
                    onChange={(event) =>
                      setFactEdits((prev) => {
                        const next = Object.assign({}, prev[row.word] || {});
                        next.text = event.target.value;
                        next.type = factType;
                        next.confidence = factConfidence;
                        return Object.assign({}, prev, { [row.word]: next });
                      })
                    }
                  />
                  <div className="enrichment-fact-footer">
                    <span>{factValue.length}/220 characters</span>
                    <select
                      value={factType}
                      onChange={(event) =>
                        setFactEdits((prev) => {
                          const next = Object.assign({}, prev[row.word] || {});
                          next.type = event.target.value;
                          next.text = factValue;
                          next.confidence = factConfidence;
                          return Object.assign({}, prev, { [row.word]: next });
                        })
                      }
                    >
                      <option value="etymology">etymology</option>
                      <option value="idiom">idiom</option>
                      <option value="trivia">trivia</option>
                    </select>
                  </div>
                  <label className="enrichment-checkbox">
                    <input
                      type="checkbox"
                      checked={Boolean(approveFact[row.word]) && canApproveFact}
                      onChange={(event) =>
                        setApproveFact((prev) =>
                          Object.assign({}, prev, { [row.word]: event.target.checked })
                        )
                      }
                      disabled={!canApproveFact}
                    />
                    Approve fact
                  </label>
                </div>
              </div>
            </section>
          );
        })
      )}

      <div className="enrichment-actions">
        <button
          type="button"
          onClick={onConfirm}
          disabled={saving || Boolean(refreshingWord)}
          className="enrichment-button enrichment-button--primary"
        >
          {saving ? "Saving…" : "Confirm & Add to List"}
        </button>
        <button
          type="button"
          onClick={onClose}
          className="enrichment-button enrichment-button--ghost"
          disabled={saving}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

window.Pavonify = window.Pavonify || {};
window.Pavonify.BulkAddEnrichmentPreview = BulkAddEnrichmentPreview;
