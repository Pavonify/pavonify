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

function extractImageUrls(list) {
  if (!Array.isArray(list)) {
    return [];
  }
  return list
    .map((img) => (img && img.url ? String(img.url).trim() : ""))
    .filter(Boolean);
}

function BulkAddEnrichmentPreview({ entries, listId, onClose, fetchImpl }) {
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
  const [refreshingKind, setRefreshingKind] = useState(null);
  const [factCache, setFactCache] = useState({});
  const [imageHistory, setImageHistory] = useState({});

  const approveAllSelectedImages = useCallback(() => {
    setApproveImage(prev => {
      const next = Object.assign({}, prev);
      (rows || []).forEach(row => {
        const choice = selectedImage[row.word];
        if (choice) {
          next[row.word] = true;
        }
      });
      return next;
    });
  }, [rows, selectedImage]);

  const approveAllFacts = useCallback(() => {
    setApproveFact(prev => {
      const next = Object.assign({}, prev);
      (rows || []).forEach(row => {
        const factState = factEdits[row.word] || {};
        const text = factState.text || "";
        if (text.trim()) {
          next[row.word] = true;
        }
      });
      return next;
    });
  }, [factEdits, rows]);

  const fetchPreviewFor = useCallback(
    async (targetEntries) => {
      const payloadEntries = (targetEntries || [])
        .map((item) => {
          if (!item) {
            return null;
          }
          const word = (item.word || "").trim();
          if (!word) {
            return null;
          }
          const translation = (item.translation || "").trim();
          const factType = item.factType;
          const validType = factType && ["etymology", "idiom", "trivia"].includes(factType) ? factType : undefined;
          const excludeImages = (item.excludeImages || [])
            .map((url) => (url ? String(url).trim() : ""))
            .filter(Boolean);
          const payload = { word, translation, fact_type: validType };
          if (excludeImages.length) {
            payload.exclude_images = excludeImages;
          }
          return payload;
        })
        .filter(Boolean);

      if (!payloadEntries.length) {
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
        body: JSON.stringify({
          list_id: listId,
          entries: payloadEntries,
        }),
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
    },
    [fetchFn, listId]
  );

  const applyInitialRows = useCallback((rowsData) => {
    const initSel = {};
    const initFact = {};
    const initCache = {};
    const initHistory = {};

    (rowsData || []).forEach((item) => {
      const images = Array.isArray(item.images) ? item.images : [];
      initSel[item.word] = images[0] || null;
      initFact[item.word] = Object.assign({}, item.fact || {});
      if (item.fact && item.fact.type) {
        initCache[item.word] = {
          [item.fact.type]: Object.assign({}, item.fact),
        };
      } else {
        initCache[item.word] = {};
      }
      initHistory[item.word] = Array.from(new Set(extractImageUrls(images)));
    });

    setRows(rowsData);
    setSelectedImage(initSel);
    setFactEdits(initFact);
    setApproveImage({});
    setApproveFact({});
    setFactCache(initCache);
    setImageHistory(initHistory);
  }, []);

  useEffect(() => {
    let active = true;

    (async () => {
      try {
        setError(null);
        setLoading(true);
        const rowsData = await fetchPreviewFor(entries || []);
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
        setFactCache({});
        setImageHistory({});
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
  }, [entries, fetchPreviewFor, applyInitialRows]);

  const refreshWord = useCallback(
    async (word, options = {}) => {
      const { refreshImages = true, refreshFact = true, factType } = options;
      if (!word) {
        return;
      }

      const currentRows = rows || [];
      const existingRow = currentRows.find((item) => item.word === word);
      const fallbackEntry = (entries || []).find((item) => item.word === word);
      const translation = (existingRow && existingRow.translation) || (fallbackEntry && fallbackEntry.translation) || "";
      const cleanedWord = word.trim();
      const effectiveFactType =
        factType ||
        (factEdits[word] && factEdits[word].type) ||
        (existingRow && existingRow.fact && existingRow.fact.type) ||
        "trivia";
      const knownExclusions = imageHistory[word] || [];
      const excludeImages = refreshImages
        ? Array.from(new Set([...knownExclusions, ...extractImageUrls(existingRow && existingRow.images)]))
        : [];

      try {
        setError(null);
        setRefreshingWord(word);
        setRefreshingKind(refreshImages && refreshFact ? "both" : refreshImages ? "images" : "fact");
        const requestEntry = { word, translation };
        if (refreshFact) {
          requestEntry.factType = effectiveFactType;
        }
        if (refreshImages && excludeImages.length) {
          requestEntry.excludeImages = excludeImages;
        }
        const rowsData = await fetchPreviewFor([requestEntry]);
        const normalized = cleanedWord.toLowerCase();
        const updatedRow =
          rowsData.find((item) => (item.word || "").trim().toLowerCase() === normalized) || rowsData[0] || null;
        if (!updatedRow) {
          throw new Error("No enrichment suggestions returned.");
        }
        const patchedRow = Object.assign({}, updatedRow, {
          translation: updatedRow.translation || translation,
        });

        const patchedImages = Array.isArray(patchedRow.images) ? patchedRow.images : [];
        const existingImages = Array.isArray(existingRow && existingRow.images) ? existingRow.images : [];
        const nextImages = refreshImages ? patchedImages : (existingImages.length ? existingImages : patchedImages);
        const nextFact = refreshFact ? patchedRow.fact : (existingRow && existingRow.fact) || patchedRow.fact;
        const resolvedFact = {
          text: nextFact && nextFact.text ? nextFact.text.trim() : "",
          type: (nextFact && nextFact.type) || effectiveFactType,
          confidence:
            typeof (nextFact && nextFact.confidence) === "number"
              ? nextFact.confidence
              : typeof (existingRow && existingRow.fact && existingRow.fact.confidence) === "number"
              ? existingRow.fact.confidence
              : typeof (patchedRow.fact && patchedRow.fact.confidence) === "number"
              ? patchedRow.fact.confidence
              : 0,
        };
        const nextRow = {
          word: cleanedWord,
          translation: patchedRow.translation || "",
          images: nextImages,
          fact: resolvedFact,
        };

        setRows((prev = []) => {
          const exists = prev.some((r) => r.word === cleanedWord);
          if (!exists) {
            return prev.concat(nextRow);
          }
          return prev.map((r) => (r.word === cleanedWord ? nextRow : r));
        });

        if (refreshImages) {
          const candidates = Array.isArray(nextImages) ? nextImages : [];
          setSelectedImage((prev) =>
            Object.assign({}, prev, {
              [cleanedWord]: candidates[0] || null,
            })
          );
          setApproveImage((prev) => Object.assign({}, prev, { [cleanedWord]: false }));
          setImageHistory((prev) => {
            const next = Object.assign({}, prev);
            const existing = Array.isArray(prev[cleanedWord]) ? prev[cleanedWord] : [];
            const merged = Array.from(new Set([...existing, ...excludeImages, ...extractImageUrls(candidates)]));
            next[cleanedWord] = merged;
            return next;
          });
        }

        if (refreshFact) {
          const baseFact = Object.assign({}, resolvedFact);
          setFactEdits((prev) =>
            Object.assign({}, prev, {
              [cleanedWord]: Object.assign({}, baseFact),
            })
          );
          setApproveFact((prev) => Object.assign({}, prev, { [cleanedWord]: false }));
          setFactCache((prev) => {
            const next = Object.assign({}, prev);
            const existing = Object.assign({}, next[cleanedWord] || {});
            if (baseFact.type) {
              existing[baseFact.type] = Object.assign({}, baseFact);
            }
            next[cleanedWord] = existing;
            return next;
          });
        }
      } catch (err) {
        setError(err && err.message ? err.message : "Failed to refresh suggestions");
      } finally {
        setRefreshingWord(null);
        setRefreshingKind(null);
      }
    },
    [entries, factEdits, fetchPreviewFor, imageHistory, rows]
  );

  const reloadAll = useCallback(async () => {
    const currentRows = rows || [];
    const baseEntries = currentRows.length
      ? currentRows.map((row) => ({
          word: row.word,
          translation:
            row.translation || ((entries || []).find((item) => item.word === row.word)?.translation || ""),
          factType: (factEdits[row.word] && factEdits[row.word].type) || (row.fact && row.fact.type),
        }))
      : (entries || []);

    if (!baseEntries.length) {
      return;
    }

    try {
      setError(null);
      setLoading(true);
      const rowsData = await fetchPreviewFor(baseEntries);
      applyInitialRows(rowsData);
    } catch (err) {
      setError(err && err.message ? err.message : "Failed to refresh suggestions");
    } finally {
      setLoading(false);
    }
  }, [applyInitialRows, entries, factEdits, fetchPreviewFor, rows]);

  const resetFactToSuggestion = (word) => {
    const row = (rows || []).find((item) => item.word === word);
    if (!row) {
      return;
    }
    const currentType = (factEdits[word] && factEdits[word].type) || (row.fact && row.fact.type) || "trivia";
    const cached = factCache[word] && factCache[word][currentType];
    setApproveFact((prev) => Object.assign({}, prev, { [word]: false }));
    if (cached) {
      setFactEdits((prev) => Object.assign({}, prev, { [word]: Object.assign({}, cached) }));
      return;
    }
    setFactEdits((prev) => {
      const next = Object.assign({}, prev);
      const existing = Object.assign({}, prev[word] || {});
      existing.type = currentType;
      existing.text = "";
      if (typeof existing.confidence !== "number") {
        existing.confidence = row.fact && row.fact.confidence;
      }
      next[word] = existing;
      return next;
    });
    refreshWord(word, { refreshImages: false, refreshFact: true, factType: currentType });
  };

  const clearImageSelection = (word) => {
    setSelectedImage((prev) => Object.assign({}, prev, { [word]: null }));
    setApproveImage((prev) => Object.assign({}, prev, { [word]: false }));
  };

  const handleFactTypeChange = useCallback(
    (word, nextType) => {
      if (!word || !nextType) {
        return;
      }
      const baseRow = (rows || []).find((item) => item.word === word);
      setFactEdits((prev) => {
        const next = Object.assign({}, prev);
        const current = Object.assign({}, prev[word] || {});
        current.type = nextType;
        current.text = "";
        if (typeof current.confidence !== "number") {
          current.confidence = baseRow && baseRow.fact ? baseRow.fact.confidence : current.confidence;
        }
        next[word] = current;
        return next;
      });
      setApproveFact((prev) => Object.assign({}, prev, { [word]: false }));
      const cached = factCache[word] && factCache[word][nextType];
      if (cached) {
        setFactEdits((prev) => Object.assign({}, prev, { [word]: Object.assign({}, cached) }));
        return;
      }
      refreshWord(word, { refreshImages: false, refreshFact: true, factType: nextType });
    },
    [factCache, refreshWord, rows]
  );

  const onConfirm = async () => {
    try {
      setSaving(true);
      setError(null);
      const items = (rows || []).map((r) => {
        const fact = factEdits[r.word] || {};
        const factText = (fact.text || "").trim();
        return {
          word: r.word,
          translation: r.translation || "",
          image: selectedImage[r.word],
          fact,
          approveImage: Boolean(approveImage[r.word] && selectedImage[r.word]),
          approveFact: Boolean(approveFact[r.word] && factText),
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
  const canBulkApproveImages = (rows || []).some((row) => Boolean(selectedImage[row.word]));
  const canBulkApproveFacts = (rows || []).some((row) => {
    const factState = factEdits[row.word] || {};
    const text = factState.text || "";
    return Boolean(text.trim());
  });

  return (
    <div className="enrichment-preview">
      <div className="enrichment-toolbar">
        <div>
          <h2>Preview Enrichments</h2>
          <p>Pick the best match for each word, then approve the items you want to add.</p>
        </div>
        <div className="enrichment-toolbar-actions">
          <button
            type="button"
            className="enrichment-button enrichment-button--ghost"
            onClick={approveAllSelectedImages}
            disabled={disableGlobalActions || !canBulkApproveImages}
          >
            Approve all selected images
          </button>
          <button
            type="button"
            className="enrichment-button enrichment-button--ghost"
            onClick={approveAllFacts}
            disabled={disableGlobalActions || !canBulkApproveFacts}
          >
            Accept all facts
          </button>
          <button
            type="button"
            className="enrichment-button enrichment-button--ghost"
            onClick={reloadAll}
            disabled={disableGlobalActions}
          >
            Refresh all suggestions
          </button>
        </div>
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
        rows.map(row => {
          const currentImage = selectedImage[row.word] || null;
          const factState = factEdits[row.word] || {};
          const factValue = factState.text || "";
          const factType = factState.type || (row.fact && row.fact.type) || "trivia";
          const factConfidence =
            typeof factState.confidence === "number"
              ? factState.confidence
              : row.fact && row.fact.confidence;
          const confidenceLabel =
            typeof factConfidence === "number" && !Number.isNaN(factConfidence)
              ? `${Math.round(Math.max(0, Math.min(1, factConfidence)) * 100)}% confidence`
              : null;
          const canApproveFact = factValue.trim().length > 0;
          const isRefreshing = refreshingWord === row.word;
          const refreshingMode = isRefreshing ? refreshingKind : null;
          const primaryWord = row.translation || row.word;
          const secondaryWord = row.translation ? row.word : "";

          return (
            <section key={row.word} className="enrichment-card">
              <div className="enrichment-card-header">
                <h3 className="enrichment-card-title">
                  {primaryWord}
                  {secondaryWord ? ` (${secondaryWord})` : ""}
                </h3>
                <div className="enrichment-card-actions">
                  <button
                    type="button"
                    className="enrichment-button enrichment-button--ghost"
                    onClick={() => refreshWord(row.word, { refreshImages: true, refreshFact: false })}
                    disabled={isRefreshing || disableGlobalActions}
                  >
                    {isRefreshing
                      ? refreshingMode === "images"
                        ? "Refreshing images…"
                        : "Refreshing…"
                      : "New image suggestions"}
                  </button>
                  <button
                    type="button"
                    className="enrichment-button enrichment-button--ghost"
                    onClick={() => refreshWord(row.word, { refreshImages: false, refreshFact: true, factType })}
                    disabled={isRefreshing || disableGlobalActions}
                  >
                    {isRefreshing
                      ? refreshingMode === "fact"
                        ? "Refreshing fact…"
                        : "Refreshing…"
                      : "New fact suggestion"}
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
                      {row.images.map(img => {
                        const selected = currentImage && currentImage.url === img.url;
                        return (
                          <button
                            type="button"
                            key={img.url}
                            className={`enrichment-thumb${selected ? " is-selected" : ""}`}
                            onClick={() => setSelectedImage(prev => Object.assign({}, prev, { [row.word]: img }))}
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
                        onChange={e => setApproveImage(prev => Object.assign({}, prev, { [row.word]: e.target.checked }))}
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
                    onChange={e =>
                      setFactEdits(prev => Object.assign({}, prev, {
                        [row.word]: Object.assign({}, prev[row.word] || { type: factType }, {
                          text: e.target.value,
                          type: factType,
                          confidence: factConfidence,
                        }),
                      }))
                    }
                    disabled={isRefreshing}
                  />
                  <div className="enrichment-fact-footer">
                    <span>{factValue.length}/220 characters</span>
                    <button
                      type="button"
                      className="enrichment-button enrichment-button--ghost"
                      onClick={() => resetFactToSuggestion(row.word)}
                      disabled={isRefreshing}
                    >
                      Reset fact text
                    </button>
                    <select
                      value={factType}
                      onChange={e => handleFactTypeChange(row.word, e.target.value)}
                      disabled={isRefreshing || disableGlobalActions}
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
                      onChange={e => setApproveFact(prev => Object.assign({}, prev, { [row.word]: e.target.checked }))}
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
        <button type="button" onClick={onClose} className="enrichment-button enrichment-button--ghost" disabled={saving}>
          Cancel
        </button>
      </div>
    </div>
  );
}

window.Pavonify = window.Pavonify || {};
window.Pavonify.BulkAddEnrichmentPreview = BulkAddEnrichmentPreview;
