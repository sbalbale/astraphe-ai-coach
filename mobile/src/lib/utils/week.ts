/**
 * Calendar weeks run Sunday → Saturday everywhere in the app (plan, Today's week strip,
 * the training log's week picker, weekly TSS, date pickers). Pass WEEK_STARTS_ON to
 * date-fns (`startOfWeek(d, { weekStartsOn: WEEK_STARTS_ON })`) and use these labels for
 * column headers so they always agree.
 */
export const WEEK_STARTS_ON = 0 as const;

/** One-letter column headers, in week order. */
export const WEEKDAY_LETTERS = ['S', 'M', 'T', 'W', 'T', 'F', 'S'] as const;

/** Three-letter uppercase column headers, in week order. */
export const WEEKDAY_SHORT = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'] as const;
