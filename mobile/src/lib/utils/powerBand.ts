const round5 = (v: number) => Math.round(v / 5) * 5;

/** Watts for a %FTP target: a ±5% FTP band rounded to 5 W. The plan, Today and planned vs
 * actual all show this same band (the plan used to show ±2.5%, a different range from the one
 * the workout was then judged against). */
export function powerBand(ftp: number, pct: number): [number, number] {
  return [round5((ftp * Math.max(0, pct - 5)) / 100), round5((ftp * (pct + 5)) / 100)];
}
