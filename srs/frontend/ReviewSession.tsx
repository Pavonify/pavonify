import React, { useCallback, useEffect, useMemo, useState } from "react";
import ExposureCard from "./cards/ExposureCard";
import TappingCard from "./cards/TappingCard";
import MCQCard from "./cards/MCQCard";
import TypingCard from "./cards/TypingCard";
import ListeningCard from "./cards/ListeningCard";
import { CardProps, CardSubmitExtra, ReviewWord } from "./types";
import { GameHubProvider } from "@/gamehub/GameHubContext";
import { useEnergyMeter } from "@/gamehub/useEnergyMeter";
import EnergyMeter from "@/gamehub/EnergyMeter";
import GameLauncherModal from "@/gamehub/GameLauncherModal";
import type { GameWord } from "@/games/PeacockConveyorSorter";

type Mode = "practice" | "assignment";

const PRACTICE_MODE: Mode = "practice";

type Props = {
  fetchImpl?: typeof fetch;
};

function getCookie(name: string): string | null {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) {
    const segment = parts.pop();
    if (segment) {
      return segment.split(";").shift() ?? null;
    }
  }
  return null;
}

function ReviewSessionInner({ fetchImpl = fetch }: Props) {
  const fetchFn = fetchImpl;
  const [queue, setQueue] = useState<ReviewWord[]>([]);
  const [current, setCurrent] = useState<ReviewWord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [launcherOpen, setLauncherOpen] = useState(false);
  const [sessionPoints, setSessionPoints] = useState(0);
  const [streak, setStreak] = useState(0);
  const { onQuestionResult } = useEnergyMeter();

  const jsonHeaders = useCallback(() => {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    const csrftoken = getCookie("csrftoken");
    if (csrftoken) headers["X-CSRFToken"] = csrftoken;
    return headers;
  }, []);

  const loadQueue = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetchFn("/api/srs/queue?limit=30&mode=mix", { credentials: "include" });
      const data: unknown = await response.json();
      const items = Array.isArray(data) ? (data as ReviewWord[]) : [];
      setQueue(items);
      setCurrent(items[0] ?? null);
    } catch (err) {
      console.error("Failed to load SRS queue", err);
      setError("Unable to load practice queue.");
      setQueue([]);
      setCurrent(null);
    } finally {
      setLoading(false);
    }
  }, [fetchFn]);

  useEffect(() => {
    loadQueue();
  }, [loadQueue]);

  useEffect(() => {
    if (queue.length > 0) {
      setCurrent(queue[0]);
    } else {
      setCurrent(null);
    }
  }, [queue]);

  const handleResult = useCallback(
    async (correct: boolean, extra: CardSubmitExtra = {}) => {
      if (!current) return;

      const payload = {
        word_id: current.word_id,
        activity_type: current.suggested_next_activity,
        is_correct: correct,
        ...extra,
      };

      const remaining = queue.slice(1);
      setQueue(remaining);
      setCurrent(remaining[0] ?? null);

      const nextStreakValue = correct ? streak + 1 : 0;
      setStreak(nextStreakValue);
      onQuestionResult({ correct, streak: nextStreakValue });

      if (correct) {
        setSessionPoints(prev => prev + 10);
      }

      try {
        await fetchFn("/api/srs/attempt", {
          method: "POST",
          headers: jsonHeaders(),
          credentials: "include",
          body: JSON.stringify(payload),
        });
      } catch (err) {
        console.error("Failed to submit attempt", err);
      } finally {
        if (remaining.length === 0) {
          await loadQueue();
        }
      }
    },
    [current, fetchFn, jsonHeaders, loadQueue, onQuestionResult, queue, streak]
  );

  const card = useMemo(() => {
    if (!current) return null;
    const cardProps: CardProps = { word: current, onSubmit: handleResult };
    switch (current.suggested_next_activity) {
      case "tapping":
        return <TappingCard {...cardProps} />;
      case "mcq":
        return <MCQCard {...cardProps} />;
      case "typing":
        return <TypingCard {...cardProps} />;
      case "listening":
        return <ListeningCard {...cardProps} />;
      default:
        return <ExposureCard {...cardProps} />;
    }
  }, [current, handleResult]);

  const fetchWords = useCallback(
    async (mode: Mode) => {
      const response = await fetchFn(`/api/srs/current-words?mode=${mode}`, {
        credentials: "include",
      });
      if (!response.ok) {
        throw new Error("Failed to load current words");
      }
      const data: unknown = await response.json();
      if (!Array.isArray(data)) {
        throw new Error("Invalid words payload");
      }
      return data as GameWord[];
    },
    [fetchFn]
  );

  const postResult = useCallback(
    async (body: unknown) => {
      const response = await fetchFn("/api/srs/game-result", {
        method: "POST",
        headers: jsonHeaders(),
        credentials: "include",
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        throw new Error("Failed to record game result");
      }
    },
    [fetchFn, jsonHeaders]
  );

  const awardSession = useCallback(
    async (body: { pointsDelta: number; streakDelta: number; energyDelta: number; tokensDelta: number }) => {
      const response = await fetchFn("/api/srs/session-award", {
        method: "POST",
        headers: jsonHeaders(),
        credentials: "include",
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        throw new Error("Failed to apply session awards");
      }
      setSessionPoints(prev => prev + (body.pointsDelta ?? 0));
      if (body.streakDelta) {
        setStreak(prev => Math.max(prev + body.streakDelta, 0));
      }
    },
    [fetchFn, jsonHeaders]
  );

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">Practice Session</h2>
          <p className="text-sm text-slate-500">Session Points: {sessionPoints}</p>
          <p className="text-sm text-slate-500">Current Streak: {streak}</p>
        </div>
        <EnergyMeter onLaunch={() => setLauncherOpen(true)} />
      </div>

      {error ? <div className="rounded-lg bg-red-50 p-4 text-sm text-red-600">{error}</div> : null}

      <div className="min-h-[200px] rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        {loading ? (
          <div className="text-center text-sm text-slate-500">Loading…</div>
        ) : card ? (
          card
        ) : (
          <div className="text-center text-sm text-slate-500">All done for now! 🎉</div>
        )}
      </div>

      <GameLauncherModal
        open={launcherOpen}
        onClose={() => setLauncherOpen(false)}
        mode={PRACTICE_MODE}
        fetchWords={fetchWords}
        postResult={postResult}
        awardSession={awardSession}
      />
    </div>
  );
}

export default function ReviewSession(props: Props) {
  return (
    <GameHubProvider>
      <ReviewSessionInner {...props} />
    </GameHubProvider>
  );
}
