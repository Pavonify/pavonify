import React, { useEffect, useState } from "react";

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
  images: ImageCandidate[];
  fact: Fact;
};

type Props = {
  words: string[];
  listId: number;
  onClose: () => void;
  fetchImpl?: typeof fetch;
};

export default function BulkAddEnrichmentPreview({
  words,
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

  useEffect(() => {
    (async () => {
      try {
        setLoading(true);
        const r = await fetchImpl("/api/vocab/enrichment/preview", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ words }),
        });
        const data: Row[] = await r.json();
        setRows(data);
        const initSel: Record<string, ImageCandidate | null> = {};
        const initFact: Record<string, Fact> = {};
        data.forEach(d => {
          initSel[d.word] = d.images[0] || null;
          initFact[d.word] = d.fact;
        });
        setSelectedImage(initSel);
        setFactEdits(initFact);
      } catch (e: any) {
        setError(e?.message || "Failed to load preview");
      } finally {
        setLoading(false);
      }
    })();
  }, [words, fetchImpl]);

  const onConfirm = async () => {
    try {
      setSaving(true);
      const items = rows.map(r => ({
        word: r.word,
        image: selectedImage[r.word],
        fact: factEdits[r.word],
        approveImage: Boolean(approveImage[r.word] && selectedImage[r.word]),
        approveFact: Boolean(approveFact[r.word] && factEdits[r.word]?.text),
      }));
      const res = await fetchImpl("/api/vocab/enrichment/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
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

  if (loading) return <div>Loading enrichments…</div>;
  if (error) return <div role="alert">Error: {error}</div>;

  return (
    <div className="p-4 space-y-4">
      <h2 className="text-xl font-semibold">Preview Enrichments</h2>
      <div className="space-y-3">
        {rows.map(row => (
          <div key={row.word} className="border rounded-lg p-3">
            <div className="font-medium mb-2">{row.word}</div>
            <div className="grid md:grid-cols-3 gap-3">
              {/* Images */}
              <div>
                <div className="text-sm mb-2">Images</div>
                <div className="flex flex-wrap gap-2">
                  {row.images.length === 0 && <div className="text-xs opacity-70">No images found</div>}
                  {row.images.map(img => {
                    const selected = selectedImage[row.word]?.url === img.url;
                    return (
                      <button
                        key={img.url}
                        onClick={() => setSelectedImage(s => ({ ...s, [row.word]: img }))}
                        className={`border rounded p-1 ${selected ? "ring-2" : ""}`}
                        title={img.attribution || ""}
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
                    onChange={e => setApproveImage(a => ({ ...a, [row.word]: e.target.checked }))}
                  />
                  Approve image
                </label>
              </div>

              {/* Fact */}
              <div className="md:col-span-2">
                <div className="text-sm mb-2">Word Fact</div>
                <textarea
                  className="w-full border rounded p-2 text-sm"
                  maxLength={220}
                  value={factEdits[row.word]?.text || ""}
                  onChange={e =>
                    setFactEdits(f => ({ ...f, [row.word]: { ...(f[row.word] || { type: "trivia" }), text: e.target.value } }))
                  }
                />
                <div className="mt-1 flex items-center gap-3 text-xs opacity-80">
                  <span>Type:
                    <select
                      className="ml-1 border rounded px-1 py-0.5"
                      value={factEdits[row.word]?.type || "trivia"}
                      onChange={e =>
                        setFactEdits(f => ({ ...f, [row.word]: { ...(f[row.word] || {}), type: e.target.value as any } }))
                      }
                    >
                      <option value="etymology">etymology</option>
                      <option value="idiom">idiom</option>
                      <option value="trivia">trivia</option>
                    </select>
                  </span>
                  <span>Chars: {(factEdits[row.word]?.text || "").length}/220</span>
                </div>
                <label className="text-sm mt-2 flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={Boolean(approveFact[row.word])}
                    onChange={e => setApproveFact(a => ({ ...a, [row.word]: e.target.checked }))}
                  />
                  Approve fact
                </label>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="flex gap-2">
        <button
          onClick={onConfirm}
          disabled={saving}
          className="px-4 py-2 rounded bg-black text-white"
        >
          {saving ? "Saving…" : "Confirm & Add to List"}
        </button>
        <button onClick={onClose} className="px-4 py-2 rounded border">Cancel</button>
      </div>
    </div>
  );
}
