import { CanvasTexture, Color, MeshBasicMaterial, SRGBColorSpace } from 'three';

import type { Modality } from '../types';

export const INK = '#2A2E29';
export const SOFT = '#7A7468';
export const ACCENT = '#D0573A';
export const ACCENT_LIGHT = '#EDBFA9';
export const CONCRETE = '#E3D9C6';
export const GRID = '#E6DCCA';

/** One hue per modality, kept apart from the accent: the accent belongs to the lit row alone. */
export const MODALITY_COLOURS: Record<Modality, string> = {
  text: '#3D6B59',
  code: '#6E9886',
  image: '#7F98AE',
  ui_screenshot: '#A7C2B2',
  video_frame: '#8C8199',
  pdf_page: '#B9824F',
  pdf_region: '#D3C29E',
  audio: '#E2AE3A',
  mixed: '#9A9284',
};

const WARM_PAPER = '#FFF8EA';
const WARM_UMBER = '#5B4434';

/** Mixes two colours in sRGB, as a painter mixes them, not in three's linear working space. */
function mix(from: string, to: string, amount: number): Color {
  const [a, b] = [new Color(from).getRGB({ r: 0, g: 0, b: 0 }, SRGBColorSpace), new Color(to).getRGB({ r: 0, g: 0, b: 0 }, SRGBColorSpace)];
  const blend = (x: number, y: number) => x + (y - x) * amount;
  return new Color().setRGB(blend(a.r, b.r), blend(a.g, b.g), blend(a.b, b.b), SRGBColorSpace);
}

/** Three flat tones per colour: top lifted toward warm paper, +z face as given, +x face dropped toward umber. */
export function tri(hex: string): MeshBasicMaterial[] {
  const face = (colour: Color) => new MeshBasicMaterial({ color: colour });
  const [lit, side, dark] = [face(mix(hex, WARM_PAPER, 0.22)), face(new Color(hex)), face(mix(hex, WARM_UMBER, 0.2))];
  return [dark, dark, lit, lit, side, side];
}

export const LATIN = '"Newsreader Variable"';
export const HAN = '"Noto Serif SC"';

/** Waits for the serif faces a label needs, so the canvas never paints a fallback font. */
export async function loadFaces(texts: string[], weight: number): Promise<void> {
  const sample = texts.join('');
  await Promise.all([
    document.fonts.load(`${weight} 64px ${LATIN}`, sample),
    document.fonts.load(`${weight} 64px ${HAN}`, sample),
  ]);
}

export interface FloorText {
  texture: CanvasTexture;
  aspect: number;
}

const GLYPH_PX = 160;

/** Paints one line of serif type on a transparent canvas, ready to lie on the floor. */
export function paintText(text: string, colour: string, weight: number): FloorText {
  const canvas = document.createElement('canvas');
  const pen = canvas.getContext('2d');
  if (!pen) {
    throw new Error('this browser gave no 2D canvas to paint floor type on');
  }
  const font = `${weight} ${GLYPH_PX}px ${LATIN}, ${HAN}, serif`;
  pen.font = font;
  const width = Math.ceil(pen.measureText(text).width) + GLYPH_PX * 0.2;
  canvas.width = width;
  canvas.height = Math.ceil(GLYPH_PX * 1.3);
  pen.font = font;
  pen.fillStyle = colour;
  pen.textBaseline = 'alphabetic';
  pen.fillText(text, GLYPH_PX * 0.1, GLYPH_PX);
  const texture = new CanvasTexture(canvas);
  texture.colorSpace = SRGBColorSpace;
  texture.anisotropy = 4;
  return { texture, aspect: canvas.width / canvas.height };
}
