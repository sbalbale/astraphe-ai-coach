/** GET /v1/weight (backend: services/weight.weight_payload). */
export type WeighIn = {
  id: string;
  /** Local calendar day of the weigh-in. */
  date: string;
  measured_at: string;
  weight_kg: number;
  body_fat_pct: number | null;
  /** manual | garmin | whoop | healthkit | intervals_icu */
  source: string;
  /** False for readings with only a date (older daily weights, a back-dated log). */
  time_known: boolean;
};

export type WeightPayload = {
  /** The athlete's local today. */
  today: string;
  /** Oldest first, last ~year, deleted ones excluded. */
  entries: WeighIn[];
  goal_weight_kg: number | null;
  ftp_watts: number | null;
  measurement_units: string | null;
};
