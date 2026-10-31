export const clamp = (x: number, a = 0, b = 1): number => Math.max(a, Math.min(b, x));
export const lerp = (a: number, b: number, t: number): number => a + (b - a) * t;
export const seg = (t: number, a: number, b: number): number => clamp((t - a) / (b - a));
export const ss = (t: number): number => {
  const c = clamp(t);
  return c * c * (3 - 2 * c);
};
export const eo = (t: number): number => 1 - Math.pow(1 - clamp(t), 3);
export const eio = (t: number): number => {
  const c = clamp(t);
  return c < 0.5 ? 4 * c * c * c : 1 - Math.pow(-2 * c + 2, 3) / 2;
};
