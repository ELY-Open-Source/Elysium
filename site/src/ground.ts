import { BufferAttribute, BufferGeometry, Mesh, MeshBasicMaterial } from 'three';
import { C } from './palette';
import { floorLayer } from './solid';

const SLAB = 4;
const LINE = 0.05;

/**
 * The faint slab grid of the one printed ground. The ground itself is the clear colour, so it runs off
 * every edge of every frame without a plane to draw.
 */
export function slabGrid(x0: number, x1: number, y0: number, y1: number): Mesh {
  const rects: [number, number, number, number][] = [];
  for (let x = Math.ceil(x0 / SLAB) * SLAB; x <= x1; x += SLAB) rects.push([x - LINE / 2, x + LINE / 2, y0, y1]);
  for (let y = Math.ceil(y0 / SLAB) * SLAB; y <= y1; y += SLAB) rects.push([x0, x1, y - LINE / 2, y + LINE / 2]);
  const pos = new Float32Array(rects.length * 18);
  rects.forEach(([a, b, c, d], i) => pos.set([a, c, 0, b, c, 0, b, d, 0, a, c, 0, b, d, 0, a, d, 0], i * 18));
  const geo = new BufferGeometry();
  geo.setAttribute('position', new BufferAttribute(pos, 3));
  return floorLayer(new Mesh(geo, new MeshBasicMaterial({ color: C.joint })), 0.002);
}
