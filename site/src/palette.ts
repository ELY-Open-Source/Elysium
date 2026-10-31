export const C = {
  paper: '#F1E8D8',
  sheet: '#FAF4E8',
  ground: '#EAE2D3',
  joint: '#E0D6C4',
  carpet: '#F2E5CE',
  carpetEdge: '#DCCAAC',
  ink: '#2A2E29',
  soft: '#7A7468',
  ghost: '#D6CCBA',
  accent: '#D0573A',
  accentLt: '#EDBFA9',
  green: '#3D6B59',
  greenLt: '#A7C2B2',
  ginger: '#E2AE3A',
  wall: '#F7F1E6',
  glass: '#C3D8D1',
  hair: '#2A2624',
  skin: '#D9A882',
  shoe: '#232524',
  screen: '#2F3532',
} as const;

export const TOPS = ['#B9824F', '#7F98AE', '#8C8199', '#D3C29E'] as const;
export const LEGS = ['#3E4450', '#59534A', '#3A3D42', '#4B4F5A'] as const;

type Rgb = [number, number, number];

function rgb(hex: string): Rgb {
  const h = hex.replace('#', '');
  if (h.length !== 6) throw new Error(`colour must be #rrggbb, got ${hex}`);
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

/** Mixes two sRGB colours the way a painter would on paper: in sRGB, not linear light. */
export function mix(a: string, b: string, t: number): string {
  const x = rgb(a);
  const y = rgb(b);
  const out = x.map((v, i) => Math.round(v + (y[i] - v) * t));
  return '#' + out.map((v) => v.toString(16).padStart(2, '0')).join('');
}

export interface Tones {
  top: string;
  base: string;
  mid: string;
  dark: string;
  /** The face that looks down; only a lid turned over shows it, paper side up. */
  under?: string;
}

/** Three tones per solid: top lifted toward warm paper, +x face the base, +y face dropped toward warm umber. */
export function tri(c: string, lift = 0.22, drop = 0.2): Tones {
  const dark = mix(c, '#5B4434', drop);
  return { top: mix(c, '#FFF8EA', lift), base: c, mid: mix(c, dark, 0.5), dark };
}
