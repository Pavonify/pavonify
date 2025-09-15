import React, { useEffect, useState } from 'react';

type Trophy = {
  id: string;
  name: string;
  category: string;
  icon: string;
  description: string;
  points: number;
};

type TrophyUnlock = {
  id: number;
  trophy: Trophy;
  earned_at: string;
  context: Record<string, unknown>;
};

export const TrophyList: React.FC = () => {
  const [unlocks, setUnlocks] = useState<TrophyUnlock[]>([]);

  useEffect(() => {
    fetch('/api/achievements/unlocks/')
      .then((res) => res.json())
      .then((data) => setUnlocks(data));
  }, []);

  return (
    <div>
      <h2>Trophies</h2>
      <ul>
        {unlocks.map((unlock) => (
          <li key={unlock.id}>
            <strong>{unlock.trophy.name}</strong> - {unlock.trophy.description}
          </li>
        ))}
      </ul>
    </div>
  );
};
