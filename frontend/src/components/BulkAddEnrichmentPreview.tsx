import React, { useCallback, useEffect, useState } from "react";

function getCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

function toPlainText(value?: string | null): string {
  if (!value) {
    return "";
  }
  return value.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
}

function extractImageUrls(list?: ImageCandidate[] | null): string[] {
  if (!Array.isArray(list)) {
    return [];
  }
  return list
    .map(img => (img?.url || "").toString().trim())
    .filter((url): url is string => Boolean(url));
}

type ImageCandidate = {
  url: string;
  thumb?: string;
  source?: string;
  attribution?: string;
  license?: string;
};

type Fact = {
  text: string;
  type: "etymology" | "idiom" | "trivia";
  confidence?: number;
};

type Row = {
  word: string;
  translation?: string;
  images: ImageCandidate[];
  fact: Fact;
};

type WordEntry = {
  word: string;
  translation?: string;
  factType?: Fact["type"];
  excludeImages?: string[];
};

type FactCache = Record<string, Partial<Record<Fact["type"], Fact>>>;

type RefreshOptions = {
  refreshImages?: boolean;
  refreshFact?: boolean;
  factType?: Fact["type"];
};

type Props = {
  entries: WordEntry[];
  listId: number;
  onClose: () => void;
  fetchImpl?: typeof fetch;
};

export default function BulkAddEnrichmentPreview({
  entries,
  listId,
  onClose,
  fetchImpl = fetch,
}: Props) {
  const [rows, setRows] = useState<Row[]>([]);
  const [selectedImage, setSelectedImage] = useState<Record<string, ImageCandidate | null>>({});
  const [approveImage, setApproveImage] = useState<Record<string, boolean>>({});
  const [factEdits, setFactEdits] = useState<Record<string, Fact>>({});
  const [approveFact, setApproveFact] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshingWord, setRefreshingWord] = useState<string | null>(null);
  const [refreshingKind, setRefreshingKind] = useState<"images" | "fact" | "both" | null>(null);
  const [factCache, setFactCache] = useState<FactCache>({});
  const [imageHistory, setImageHistory] = useState<Record<string, string[]>>({});

  const approveAllSelectedImages = useCallback(() => {
    setApproveImage(prev => {
      const next = { ...prev };
      rows.forEach(row => {
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
      const next = { ...prev };
      rows.forEach(row => {
        const text = (factEdits[row.word]?.text || "").trim();
        if (text) {
          next[row.word] = true;
        }
      });
      return next;
    });
  }, [factEdits, rows]);

  const fetchPreviewFor = useCallback(
    async (targetEntries: WordEntry[]): Promise<Row[]> => {
      const payloadEntries = (targetEntries || [])
        .map(item => {
          const word = (item.word || "").trim();
          if (!word) {
            return null;
          }
          const translation = (item.translation || "").trim();
          const factType = item.factType;
          const excludeImages = (item.excludeImages || [])
            .map(url => (url || "").toString().trim())
            .filter(url => Boolean(url));
          return {
            word,
            translation,
            fact_type: factType && ["etymology", "idiom", "trivia"].includes(factType) ? factType : undefined,
            exclude_images: excludeImages.length ? excludeImages : undefined,
          };
        })
        .filter(
          (
            entry,
          ): entry is {
            word: string;
            translation: string;
            fact_type?: Fact["type"];
            exclude_images?: string[];
          } => Boolean(entry)
        );

      if (!payloadEntries.length) {
        return [];
      }

      const headers: Record<string, string> = { "Content-Type": "application/json" };
      const csrfToken = getCookie("csrftoken");
      if (csrfToken) {
        headers["X-CSRFToken"] = csrfToken;
      }

      const response = await fetchImpl("/api/vocab/enrichment/preview", {
        method: "POST",
        headers,
        credentials: "include",
        body: JSON.stringify({
          list_id: listId,
          entries: payloadEntries,
        }),
      });

      let data: unknown = null;
      try {
        data = await response.json();
      } catch (err) {
        if (!response.ok) {
          throw new Error("Failed to load preview");
        }
        throw err;
      }

      if (!response.ok) {
        const detail =
          data && typeof data === "object" && "detail" in data ? (data as { detail?: string }).detail : null;
        throw new Error(detail || "Failed to load preview");
      }

      if (!Array.isArray(data)) {
        throw new Error("Unexpected response from server");
      }

      return data as Row[];
    },
    [fetchImpl, listId]
  );

  const applyInitialRows = useCallback((rowsData: Row[]) => {
    const initSel: Record<string, ImageCandidate | null> = {};
    const initFact: Record<string, Fact> = {};
    const initCache: FactCache = {};
    const initHistory: Record<string, string[]> = {};

    rowsData.forEach(item => {
      const images = Array.isArray(item.images) ? item.images : [];
      initSel[item.word] = images[0] || null;
      initFact[item.word] = { ...item.fact };
      if (item.fact?.type) {
        initCache[item.word] = {
          [item.fact.type]: { ...item.fact },
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
        const rowsData = await fetchPreviewFor(entries);
        if (!active) {
          return;
        }
        applyInitialRows(rowsData);
      } catch (err: any) {
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
        setError(err?.message || "Failed to load preview");
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
    async (word: string, options: RefreshOptions = {}) => {
      const { refreshImages = true, refreshFact = true, factType } = options;
      if (!word) {
        return;
      }

      const existingRow = rows.find(item => item.word === word);
      const fallbackEntry = entries.find(item => item.word === word);
      const translation = existingRow?.translation || fallbackEntry?.translation || "";
      const cleanedWord = word.trim();
      const effectiveFactType = (factType || factEdits[word]?.type || existingRow?.fact.type || "trivia") as Fact["type"];
      const knownExclusions = imageHistory[word] || [];
      const excludeImages = refreshImages
        ? Array.from(new Set([...knownExclusions, ...extractImageUrls(existingRow?.images)]))
        : [];

      try {
        setError(null);
        setRefreshingWord(word);
        setRefreshingKind(refreshImages && refreshFact ? "both" : refreshImages ? "images" : "fact");
        const requestEntry: WordEntry = {
          word,
          translation,
          factType: refreshFact ? effectiveFactType : undefined,
          excludeImages: refreshImages ? excludeImages : undefined,
        };
        const rowsData = await fetchPreviewFor([requestEntry]);
        const normalized = word.trim().toLowerCase();
        const updatedRow =
          rowsData.find(item => item.word.trim().toLowerCase() === normalized) || rowsData[0] || null;
        if (!updatedRow) {
          throw new Error("No enrichment suggestions returned.");
        }
        const patchedRow: Row = {
          ...updatedRow,
          translation: updatedRow.translation || translation,
        };

        const patchedImages = Array.isArray(patchedRow.images) ? patchedRow.images : [];
        const existingImages = Array.isArray(existingRow?.images) ? existingRow?.images ?? [] : [];
        const nextImages = refreshImages ? patchedImages : existingImages.length ? existingImages : patchedImages;
        const nextFact = refreshFact ? patchedRow.fact : existingRow?.fact || patchedRow.fact;
        const resolvedFact: Fact = {
          text: (nextFact?.text || "").trim(),
          type: (nextFact?.type || effectiveFactType) as Fact["type"],
          confidence:
            typeof nextFact?.confidence === "number"
              ? nextFact.confidence
              : typeof existingRow?.fact?.confidence === "number"
              ? existingRow.fact.confidence
              : typeof patchedRow.fact?.confidence === "number"
              ? patchedRow.fact.confidence
              : 0,
        };
        const nextRow: Row = {
          word: cleanedWord,
          translation: patchedRow.translation || "",
          images: nextImages,
          fact: resolvedFact,
        };

        setRows(prev => {
          const exists = prev.some(r => r.word === cleanedWord);
          if (!exists) {
            return [...prev, nextRow];
          }
          return prev.map(r => (r.word === cleanedWord ? nextRow : r));
        });

        if (refreshImages) {
          const candidates = Array.isArray(nextImages) ? nextImages : [];
          setSelectedImage(prev => ({
            ...prev,
            [cleanedWord]: candidates[0] || null,
          }));
          setApproveImage(prev => ({ ...prev, [cleanedWord]: false }));
          setImageHistory(prev => {
            const next = { ...prev };
            const existing = Array.isArray(prev[cleanedWord]) ? prev[cleanedWord] : [];
            const merged = Array.from(new Set([...existing, ...excludeImages, ...extractImageUrls(candidates)]));
            next[cleanedWord] = merged;
            return next;
          });
        }

        if (refreshFact) {
          const baseFact: Fact = { ...resolvedFact };
          setFactEdits(prev => ({
            ...prev,
            [cleanedWord]: { ...baseFact },
          }));
          setApproveFact(prev => ({ ...prev, [cleanedWord]: false }));
          setFactCache(prev => {
            const next = { ...prev };
            const existingCache = { ...(next[cleanedWord] || {}) };
            if (baseFact?.type) {
              existingCache[baseFact.type] = { ...baseFact };
            }
            next[cleanedWord] = existingCache;
            return next;
          });
        }
      } catch (err: any) {
        setError(err?.message || "Failed to refresh suggestions");
      } finally {
        setRefreshingWord(null);
        setRefreshingKind(null);
      }
    },
    [entries, factEdits, fetchPreviewFor, imageHistory, rows]
  );

  const reloadAll = useCallback(async () => {
    const requestEntries: WordEntry[] = rows.length
      ? rows.map(row => ({
          word: row.word,
          translation: row.translation || entries.find(item => item.word === row.word)?.translation || "",
          factType: (factEdits[row.word]?.type || row.fact.type) as Fact["type"],
        }))
      : entries;

    if (!requestEntries.length) {
      return;
    }

    try {
      setError(null);
      setLoading(true);
      const rowsData = await fetchPreviewFor(requestEntries);
      applyInitialRows(rowsData);
    } catch (err: any) {
      setError(err?.message || "Failed to refresh suggestions");
    } finally {
      setLoading(false);
    }
  }, [applyInitialRows, entries, factEdits, fetchPreviewFor, rows]);

  const resetFactToSuggestion = (word: string) => {
    const row = rows.find(item => item.word === word);
    if (!row) {
      return;
    }
    const currentType = (factEdits[word]?.type || row.fact.type || "trivia") as Fact["type"];
    const cached = factCache[word]?.[currentType];
    setApproveFact(prev => ({ ...prev, [word]: false }));
    if (cached) {
      setFactEdits(prev => ({ ...prev, [word]: { ...cached } }));
      return;
    }
    setFactEdits(prev => ({
      ...prev,
      [word]: {
        ...(prev[word] || {}),
        type: currentType,
        text: "",
        confidence: prev[word]?.confidence ?? row.fact.confidence,
      },
    }));
    void refreshWord(word, { refreshImages: false, refreshFact: true, factType: currentType });
  };

  const clearImageSelection = (word: string) => {
    setSelectedImage(prev => ({ ...prev, [word]: null }));
    setApproveImage(prev => ({ ...prev, [word]: false }));
  };

  const handleFactTypeChange = useCallback(
    (word: string, nextType: Fact["type"]) => {
      if (!word || !nextType) {
        return;
      }
      const baseRow = rows.find(item => item.word === word);
      setFactEdits(prev => {
        const current = { ...(prev[word] || {}) } as Fact;
        current.type = nextType;
        current.text = "";
        if (typeof current.confidence !== "number") {
          current.confidence = baseRow?.fact.confidence;
        }
        return { ...prev, [word]: current };
      });
      setApproveFact(prev => ({ ...prev, [word]: false }));
      const cached = factCache[word]?.[nextType];
      if (cached) {
        setFactEdits(prev => ({ ...prev, [word]: { ...cached } }));
        return;
      }
      void refreshWord(word, { refreshImages: false, refreshFact: true, factType: nextType });
    },
    [factCache, refreshWord, rows]
  );

  const onConfirm = async () => {
    try {
      setSaving(true);
      setError(null);
      const items = rows.map(r => ({
        word: r.word,
        translation: r.translation || "",
        image: selectedImage[r.word],
        fact: factEdits[r.word],
        approveImage: Boolean(approveImage[r.word] && selectedImage[r.word]),
        approveFact: Boolean(approveFact[r.word] && (factEdits[r.word]?.text || "").trim()),
      }));
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      const csrfToken = getCookie("csrftoken");
      if (csrfToken) {
        headers["X-CSRFToken"] = csrfToken;
      }
      const res = await fetchImpl("/api/vocab/enrichment/confirm", {
        method: "POST",
        headers,
        credentials: "include",
        body: JSON.stringify({ list_id: listId, items }),
      });
      if (!res.ok) throw new Error("Save failed");
      onClose();
    } catch (e: any) {
      setError(e?.message || "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="enrichment-loading">Loading enrichments…</div>;
  }

  const disableGlobalActions = Boolean(refreshingWord) || saving;
  const canBulkApproveImages = rows.some(row => Boolean(selectedImage[row.word]));
  const canBulkApproveFacts = rows.some(row => Boolean((factEdits[row.word]?.text || "").trim()));

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
          const factValue = factEdits[row.word]?.text || "";
          const factType = (factEdits[row.word]?.type || row.fact.type || "trivia") as Fact["type"];
          const factConfidence = factEdits[row.word]?.confidence ?? row.fact.confidence;
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

                  {row.images.length > 0 && (
                    <div className="enrichment-thumb-list">
                      {row.images.map(img => {
                        const selected = currentImage?.url === img.url;
                        return (
                          <button
                            type="button"
                            key={img.url}
                            className={`enrichment-thumb${selected ? " is-selected" : ""}`}
                            onClick={() => setSelectedImage(prev => ({ ...prev, [row.word]: img }))}
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
                        onChange={e => setApproveImage(prev => ({ ...prev, [row.word]: e.target.checked }))}
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
                      setFactEdits(prev => ({
                        ...prev,
                        [row.word]: {
                          ...(prev[row.word] || { type: factType }),
                          text: e.target.value,
                          type: factType,
                          confidence: factConfidence,
                        },
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
                    onChange={e => handleFactTypeChange(row.word, e.target.value as Fact["type"])}
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
                      onChange={e => setApproveFact(prev => ({ ...prev, [row.word]: e.target.checked }))}
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
