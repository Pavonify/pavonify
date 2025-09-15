const { useEffect, useState } = React;

function getCookie(name) {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
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

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const headers = { "Content-Type": "application/json" };
        const csrfToken = getCookie("csrftoken");
        if (csrfToken) {
          headers["X-CSRFToken"] = csrfToken;
        }
        const response = await fetchFn("/api/vocab/enrichment/preview", {
          method: "POST",
          headers,
          credentials: "include",
          body: JSON.stringify({ words }),
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
          const detail = data && typeof data === "object" && "detail" in data ? data.detail : null;
          throw new Error(detail || "Failed to load preview");
        }
        if (!Array.isArray(data)) {
          throw new Error("Unexpected response from server");
        }
        if (!active) {
          return;
        }
        setRows(data);
        const initSel = {};
        const initFact = {};
        data.forEach((d) => {
          initSel[d.word] = (d.images && d.images[0]) || null;
          initFact[d.word] = d.fact;
        });
        setSelectedImage(initSel);
        setFactEdits(initFact);
      } catch (e) {
        if (!active) {
          return;
        }
        setError(e && e.message ? e.message : "Failed to load preview");
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    })();
    return () => {
      active = false;
    };
  }, [words, fetchFn]);

  const onConfirm = async () => {
    try {
      setSaving(true);
      setError(null);
      const items = rows.map((r) => ({
        word: r.word,
        image: selectedImage[r.word],
        fact: factEdits[r.word],
        approveImage: Boolean(approveImage[r.word] && selectedImage[r.word]),
        approveFact: Boolean(approveFact[r.word] && factEdits[r.word] && factEdits[r.word].text),
      }));
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
    } catch (e) {
      setError(e && e.message ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div>Loading enrichments…</div>;
  }
  if (error) {
    return <div role="alert">Error: {error}</div>;
  }

  return (
    <div className="p-4 space-y-4">
      <h2 className="text-xl font-semibold">Preview Enrichments</h2>
      <div className="space-y-3">
        {rows.map((row) => (
          <div key={row.word} className="border rounded-lg p-3">
            <div className="font-medium mb-2">{row.word}</div>
            <div className="grid md:grid-cols-3 gap-3">
              <div>
                <div className="text-sm mb-2">Images</div>
                <div className="flex flex-wrap gap-2">
                  {row.images.length === 0 && (
                    <div className="text-xs opacity-70">No images found</div>
                  )}
                  {row.images.map((img) => {
                    const selected = selectedImage[row.word] && selectedImage[row.word].url === img.url;
                    return (
                      <button
                        key={img.url}
                        onClick={() =>
                          setSelectedImage((state) => ({
                            ...state,
                            [row.word]: img,
                          }))
                        }
                        className={`border rounded p-1 ${selected ? "ring-2" : ""}`}
                        title={img.attribution || ""}
                        type="button"
                      >
                        <img src={img.thumb || img.url} alt={row.word} className="h-16 w-16 object-cover" />
                      </button>
                    );
                  })}
                </div>
                <label className="text-sm mt-2 flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={Boolean(approveImage[row.word])}
                    onChange={(event) =>
                      setApproveImage((state) => ({
                        ...state,
                        [row.word]: event.target.checked,
                      }))
                    }
                  />
                  Approve image
                </label>
              </div>

              <div className="md:col-span-2">
                <div className="text-sm mb-2">Word Fact</div>
                <textarea
                  className="w-full border rounded p-2 text-sm"
                  maxLength={220}
                  value={(factEdits[row.word] && factEdits[row.word].text) || ""}
                  onChange={(event) =>
                    setFactEdits((state) => ({
                      ...state,
                      [row.word]: {
                        ...(state[row.word] || { type: "trivia" }),
                        text: event.target.value,
                      },
                    }))
                  }
                />
                <div className="mt-1 flex items-center gap-3 text-xs opacity-80">
                  <span>
                    Type:
                    <select
                      className="ml-1 border rounded px-1 py-0.5"
                      value={(factEdits[row.word] && factEdits[row.word].type) || "trivia"}
                      onChange={(event) =>
                        setFactEdits((state) => ({
                          ...state,
                          [row.word]: {
                            ...(state[row.word] || {}),
                            type: event.target.value,
                          },
                        }))
                      }
                    >
                      <option value="etymology">etymology</option>
                      <option value="idiom">idiom</option>
                      <option value="trivia">trivia</option>
                    </select>
                  </span>
                  <span>
                    Chars: {((factEdits[row.word] && factEdits[row.word].text) || "").length}/220
                  </span>
                </div>
                <label className="text-sm mt-2 flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={Boolean(approveFact[row.word])}
                    onChange={(event) =>
                      setApproveFact((state) => ({
                        ...state,
                        [row.word]: event.target.checked,
                      }))
                    }
                  />
                  Approve fact
                </label>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="flex gap-2">
        <button onClick={onConfirm} disabled={saving} className="px-4 py-2 rounded bg-black text-white" type="button">
          {saving ? "Saving…" : "Confirm & Add to List"}
        </button>
        <button onClick={onClose} className="px-4 py-2 rounded border" type="button">
          Cancel
        </button>
      </div>
    </div>
  );
}

window.Pavonify = window.Pavonify || {};
window.Pavonify.BulkAddEnrichmentPreview = BulkAddEnrichmentPreview;
