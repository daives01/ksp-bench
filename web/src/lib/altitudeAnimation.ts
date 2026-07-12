const ALTITUDE_LINE_STAGGER_MS = 90;

export function altitudeAnimationDelay(index: number): string {
  return `${index * ALTITUDE_LINE_STAGGER_MS}ms`;
}
