import type { PlotMark } from "../../api/pinpoint";

export const MAX_MARKS = 9;

/** The smallest free number, so a removed mark's number is reused first. */
export function nextMarkNumber(marks: PlotMark[]): number | null {
  const used = new Set(marks.map((mark) => mark.number));
  for (let number = 1; number <= MAX_MARKS; number += 1)
    if (!used.has(number)) return number;
  return null;
}

export function describeMark(mark: PlotMark) {
  return `${mark.kind === "point" ? "Point" : "Area"} ${mark.number}`;
}
