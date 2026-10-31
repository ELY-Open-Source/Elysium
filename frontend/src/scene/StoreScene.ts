import {
  Box3,
  BoxGeometry,
  BufferGeometry,
  Float32BufferAttribute,
  Group,
  LineBasicMaterial,
  LineSegments,
  Mesh,
  MeshBasicMaterial,
  OrthographicCamera,
  PlaneGeometry,
  Raycaster,
  Scene,
  Vector2,
  Vector3,
  WebGLRenderer,
} from 'three';

import { formatNumber } from '../lib/format';
import type { Shelf, StoreShape } from '../lib/shelves';
import { ACCENT, ACCENT_LIGHT, CONCRETE, GRID, INK, loadFaces, MODALITY_COLOURS, paintText, SOFT, tri } from './paint';

// World metres: a shelf runs along -z (up-right on screen), shelves step along +x toward the viewer.
const COLUMN = 1.3;
const BOX = 0.84;
const BOX_H = 0.18;
const BOX_GAP = 0.05;
const NAME_RUN = 4.2;
const PLINTH_H = 0.1;
const LABEL_WEIGHT = 600;
const MIN_PITCH = 2.6;
// A stack hides the floor behind it as deep as it is tall, so the next shelf keeps that much clear.
const CLEAR_BEHIND = 1.4;

/** Boxes in a stack: each box doubles the count it can stand for. */
function boxesFor(count: number): number {
  return Math.ceil(Math.log2(count + 1));
}

interface Grower {
  mesh: Mesh;
  delay: number;
  fade?: MeshBasicMaterial;
}

const GROW_SECONDS = 0.6;
const PUSH_FROM = 0.93;
const PUSH_SECONDS = 2.4;
// A redraw with the same counts (only the lit shelf moved) starts already settled.
const SETTLED_MS = 60_000;
const easeOut = (t: number) => 1 - (1 - t) ** 3;

export class StoreScene {
  private readonly renderer: WebGLRenderer;
  private readonly camera = new OrthographicCamera();
  private readonly scene = new Scene();
  private readonly raycaster = new Raycaster();
  private readonly materials = new Map<string, MeshBasicMaterial[]>();
  private readonly boxGeometry = new BoxGeometry(BOX, BOX_H, BOX).translate(0, BOX_H / 2, 0);
  private world = new Group();
  private growers: Grower[] = [];
  private started = 0;
  private round = 0;
  private layout = '';
  private readonly picked: (holder: string) => void;
  private readonly host: HTMLElement;
  private readonly still: boolean;

  constructor(host: HTMLElement, onPick: (holder: string) => void) {
    this.host = host;
    this.picked = onPick;
    this.still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    this.renderer = new WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setClearColor(0x000000, 0);
    host.appendChild(this.renderer.domElement);
    this.renderer.domElement.addEventListener('click', this.onClick);
    this.scene.add(this.world);
  }

  /** Rebuilds the store from counts; boxes grow in reading order unless the viewer asked for stillness. */
  async show(shape: StoreShape): Promise<void> {
    const rows = shape.others ? [...shape.shelves, shape.others] : shape.shelves;
    const names = rows.map((row) => row.holder || 'others');
    const numerals = rows.flatMap((row) => row.counts.map(formatNumber));
    const round = ++this.round;
    await loadFaces([...names, ...numerals], LABEL_WEIGHT);
    if (round !== this.round) {
      return;
    }
    this.clear();
    const tallest = Math.max(1, ...rows.flatMap((row) => row.counts.map(boxesFor))) * (BOX_H + BOX_GAP);
    const pitch = Math.max(MIN_PITCH, tallest + CLEAR_BEHIND);
    rows.forEach((row, index) => this.addShelf(row, index * pitch, index, shape, row.holder !== '' && row.holder === shape.lit));
    this.addGrid(NAME_RUN + shape.modalities.length * COLUMN, (rows.length - 1) * pitch);
    this.fit();
    const layout = JSON.stringify([shape.modalities, rows.map((row) => [row.holder, row.counts])]);
    this.started = layout === this.layout ? performance.now() - SETTLED_MS : performance.now();
    this.layout = layout;
    this.renderer.setAnimationLoop(this.tick);
  }

  resize(): void {
    const { clientWidth, clientHeight } = this.host;
    this.renderer.setSize(clientWidth, clientHeight);
    this.fit();
    this.renderer.render(this.scene, this.camera);
  }

  destroy(): void {
    this.round += 1;
    this.renderer.setAnimationLoop(null);
    this.renderer.domElement.removeEventListener('click', this.onClick);
    this.clear();
    this.boxGeometry.dispose();
    for (const set of this.materials.values()) {
      set.forEach((material) => material.dispose());
    }
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }

  private toned(hex: string): MeshBasicMaterial[] {
    let set = this.materials.get(hex);
    if (!set) {
      set = tri(hex);
      this.materials.set(hex, set);
    }
    return set;
  }

  private addShelf(row: Shelf, x: number, index: number, shape: StoreShape, lit: boolean): void {
    const run = shape.modalities.length * COLUMN;
    const plinth = new Mesh(new BoxGeometry(BOX + 0.36, PLINTH_H, run + 0.3), this.toned(lit ? ACCENT_LIGHT : CONCRETE));
    plinth.position.set(x, PLINTH_H / 2, -(NAME_RUN + run / 2));
    plinth.userData.holder = row.holder;
    this.world.add(plinth);

    const ink = lit ? ACCENT : INK;
    const name = this.floorLabel(row.holder || 'others', row.holder ? ink : SOFT, 0.95, NAME_RUN - 0.6, index * 0.14);
    name.mesh.position.set(x, 0.004, -(NAME_RUN - 0.3 - name.width / 2));

    row.counts.forEach((count, column) => {
      const along = NAME_RUN + column * COLUMN + COLUMN / 2;
      const material = this.toned(MODALITY_COLOURS[shape.modalities[column]]);
      for (let level = 0; level < boxesFor(count); level += 1) {
        const box = new Mesh(this.boxGeometry, material);
        box.position.set(x, PLINTH_H + level * (BOX_H + BOX_GAP), -along);
        box.userData.holder = row.holder;
        this.world.add(box);
        this.growers.push({ mesh: box, delay: index * 0.12 + column * 0.05 + level * 0.04 });
      }
      const numeral = this.floorLabel(formatNumber(count), count > 0 ? INK : SOFT, 0.5, COLUMN - 0.15, index * 0.14 + 0.2);
      numeral.mesh.position.set(x + BOX / 2 + 0.55, 0.004, -(along - COLUMN / 2 + 0.1 + numeral.width / 2));
    });
  }

  /** Serif type lying flat on the floor, baseline along -z and glyph tops toward -x; the caller places it. */
  private floorLabel(text: string, colour: string, size: number, fit: number, delay: number): { mesh: Mesh; width: number } {
    const { texture, aspect } = paintText(text, colour, LABEL_WEIGHT);
    const height = Math.min(size, fit / aspect);
    const width = height * aspect;
    const material = new MeshBasicMaterial({ map: texture, transparent: true, depthWrite: false, opacity: 0 });
    const label = new Mesh(new PlaneGeometry(width, height), material);
    label.rotation.set(-Math.PI / 2, Math.PI / 2, 0, 'YXZ');
    label.renderOrder = 1;
    this.world.add(label);
    this.growers.push({ mesh: label, delay, fade: material });
    return { mesh: label, width };
  }

  /** A faint one-metre slab grid under the shelves, one metre past them on every side. */
  private addGrid(run: number, depth: number): void {
    const points: number[] = [];
    const [near, far] = [-1, Math.ceil(depth) + 2];
    const [start, end] = [0, -Math.ceil(run + 1)];
    for (let x = near; x <= far; x += 1) {
      points.push(x, 0, start, x, 0, end);
    }
    for (let z = start; z >= end; z -= 1) {
      points.push(near, 0, z, far, 0, z);
    }
    const geometry = new BufferGeometry();
    geometry.setAttribute('position', new Float32BufferAttribute(points, 3));
    this.world.add(new LineSegments(geometry, new LineBasicMaterial({ color: GRID })));
  }

  private fit(): void {
    const { clientWidth, clientHeight } = this.host;
    if (clientWidth === 0 || clientHeight === 0) {
      return;
    }
    const bounds = new Box3().setFromObject(this.world);
    if (bounds.isEmpty()) {
      return;
    }
    const centre = bounds.getCenter(new Vector3());
    this.camera.position.copy(centre).add(new Vector3(60, 60, 60));
    this.camera.lookAt(centre);
    this.camera.updateMatrixWorld();
    const view = new Box3();
    const { min, max } = bounds;
    for (const corner of [
      [min.x, min.y, min.z], [max.x, min.y, min.z], [min.x, max.y, min.z], [min.x, min.y, max.z],
      [max.x, max.y, min.z], [max.x, min.y, max.z], [min.x, max.y, max.z], [max.x, max.y, max.z],
    ]) {
      view.expandByPoint(new Vector3(...corner).applyMatrix4(this.camera.matrixWorldInverse));
    }
    const aspect = clientWidth / clientHeight;
    let width = (view.max.x - view.min.x) * 1.04;
    let height = (view.max.y - view.min.y) * 1.08;
    if (width / height > aspect) {
      height = width / aspect;
    } else {
      width = height * aspect;
    }
    const middle = view.getCenter(new Vector3());
    Object.assign(this.camera, {
      left: middle.x - width / 2,
      right: middle.x + width / 2,
      top: middle.y + height / 2,
      bottom: middle.y - height / 2,
      near: 1,
      far: 400,
    });
    this.camera.updateProjectionMatrix();
  }

  private readonly tick = (): void => {
    const seconds = (performance.now() - this.started) / 1000;
    let moving = !this.still && seconds < PUSH_SECONDS;
    this.camera.zoom = this.still ? 1 : PUSH_FROM + (1 - PUSH_FROM) * easeOut(Math.min(1, seconds / PUSH_SECONDS));
    this.camera.updateProjectionMatrix();
    for (const grower of this.growers) {
      const t = this.still ? 1 : Math.min(1, Math.max(0, (seconds - grower.delay) / GROW_SECONDS));
      moving ||= t < 1;
      const eased = easeOut(t);
      if (grower.fade) {
        grower.fade.opacity = eased;
        grower.mesh.scale.setScalar(1.22 - 0.22 * eased);
      } else {
        grower.mesh.scale.set(1, Math.max(eased, 0.001), 1);
      }
    }
    this.renderer.render(this.scene, this.camera);
    if (!moving) {
      this.renderer.setAnimationLoop(null);
      this.host.dataset.drawn = 'yes';
    }
  };

  private readonly onClick = (event: MouseEvent): void => {
    const area = this.renderer.domElement.getBoundingClientRect();
    const pointer = new Vector2(((event.clientX - area.left) / area.width) * 2 - 1, -((event.clientY - area.top) / area.height) * 2 + 1);
    this.raycaster.setFromCamera(pointer, this.camera);
    const hit = this.raycaster.intersectObjects(this.world.children).find((found) => typeof found.object.userData.holder === 'string');
    if (hit) {
      this.picked(hit.object.userData.holder as string);
    }
  };

  private clear(): void {
    this.renderer.setAnimationLoop(null);
    delete this.host.dataset.drawn;
    this.world.traverse((node) => {
      if (!(node instanceof Mesh || node instanceof LineSegments)) {
        return;
      }
      if (node.geometry !== this.boxGeometry) {
        node.geometry.dispose();
      }
      // Toned solids share the cached three-tone arrays; only labels and the grid own their material.
      if (!Array.isArray(node.material)) {
        const material = node.material as MeshBasicMaterial;
        material.map?.dispose();
        material.dispose();
      }
    });
    this.scene.remove(this.world);
    this.world = new Group();
    this.scene.add(this.world);
    this.growers = [];
  }
}
