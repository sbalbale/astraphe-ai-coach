export type WorkoutZone = 'Recovery' | 'Endurance' | 'Tempo' | 'Threshold' | 'VO2Max' | 'Anaerobic';

export interface Interval {
  name: string;
  duration_minutes: number;
  target_power_percent_ftp?: number;
  target_hr_zone?: number;
  description?: string;
}

export interface Workout {
  id: string;
  date: string; // ISO format YYYY-MM-DD
  title: string;
  sport: 'run' | 'bike' | 'swim' | 'row' | 'strength' | 'mobility' | 'other';
  primary_zone: WorkoutZone;
  duration_minutes: number;
  projected_tss: number;
  description: string;
  structure: Interval[];
  completed: boolean;
  /** Recorded workout that completed this session (null when done by hand or not done). */
  completed_workout_id?: string | null;
  link_source?: 'auto' | 'manual' | null;
  linked_workout?: import('./linking').LinkedWorkout | null;
}

