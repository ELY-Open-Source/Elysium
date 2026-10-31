import { Raycaster, Vector2, type Object3D } from 'three';
import type { Hover } from './beat';
import type { Stage } from './stage';

function shown(o: Object3D | null): boolean {
  for (let n = o; n; n = n.parent) if (!n.visible && n !== o) return false;
  return true;
}

function fill(card: HTMLElement, h: Hover): void {
  const template = document.getElementById(h.card);
  if (!(template instanceof HTMLTemplateElement)) throw new Error(`no <template id="${h.card}"> for a hover card`);
  card.replaceChildren(template.content.cloneNode(true));
  const slot = card.querySelector('[data-slot="label"]');
  if (slot) {
    if (!h.label) throw new Error(`card "${h.card}" has a label slot but the person has no label`);
    slot.textContent = h.label;
  }
}

/** Pointing at (or tapping) a person shows the memory card they hold, as real text. */
export function memoryCards(stage: Stage, people: Hover[]): void {
  const card = document.getElementById('memory-card');
  if (!card) throw new Error('index.html has no #memory-card');
  const ray = new Raycaster();
  const ndc = new Vector2();
  let current: Hover | null = null;

  const pick = (x: number, y: number): Hover | null => {
    ndc.set((x / window.innerWidth) * 2 - 1, -(y / window.innerHeight) * 2 + 1);
    ray.setFromCamera(ndc, stage.camera);
    const live = people.filter((h) => h.person.dim > 0.5 && shown(h.person.hit));
    const hit = ray.intersectObjects(live.map((h) => h.person.hit), false)[0];
    return hit ? (live.find((h) => h.person.hit === hit.object) ?? null) : null;
  };

  const show = (h: Hover | null, x: number, y: number): void => {
    document.documentElement.classList.toggle('pointing', h !== null);
    if (!h) {
      card.hidden = true;
      current = null;
      return;
    }
    if (h !== current) fill(card, h);
    current = h;
    card.hidden = false;
    const w = card.offsetWidth;
    const hgt = card.offsetHeight;
    card.style.left = `${Math.min(x + 16, window.innerWidth - w - 8)}px`;
    card.style.top = `${Math.max(8, y - hgt - 12)}px`;
  };

  const overUi = (e: PointerEvent): boolean => e.target instanceof Element && e.target.closest('.cue.on, a, button') !== null;
  window.addEventListener('pointermove', (e) => {
    if (e.pointerType === 'touch') return;
    show(overUi(e) ? null : pick(e.clientX, e.clientY), e.clientX, e.clientY);
  });
  window.addEventListener('pointerdown', (e) => {
    if (e.pointerType !== 'touch' || overUi(e)) return;
    show(pick(e.clientX, e.clientY), e.clientX, e.clientY);
  });
  window.addEventListener('scroll', () => show(null, 0, 0), { passive: true });
}
