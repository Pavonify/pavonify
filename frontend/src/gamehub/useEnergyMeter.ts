import { useGameHub } from "./GameHubContext";

type QuestionResult = {
  correct: boolean;
  streak: number;
};

export function useEnergyMeter() {
  const hub = useGameHub();

  function onQuestionResult({ correct, streak }: QuestionResult) {
    if (correct) hub.gainEnergy(1, streak);
  }

  return { ...hub, onQuestionResult };
}
