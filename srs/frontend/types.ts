export type ReviewWord = {
  word_id?: number;
  prompt?: string;
  answer?: string;
  choices?: string[];
  audio?: string;
  suggested_next_activity?: string;
  [key: string]: unknown;
};

export type CardSubmitExtra = Record<string, unknown>;

export type CardProps = {
  word: ReviewWord;
  onSubmit: (correct: boolean, extra?: CardSubmitExtra) => void | Promise<void>;
};
