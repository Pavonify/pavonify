import { useGameHub } from "./GameHubContext.js";

export function useEnergyMeter() {
  const hub = useGameHub();

  function onQuestionResult({ correct, streak }) {
    if (correct) {
      hub.gainEnergy(1, streak);
    }
  }

  return { ...hub, onQuestionResult };
}
