import 'lenis/dist/lenis.css';
import './style.css';
import { Group } from 'three';
import { T, type Beat } from './beat';
import { opening, INTRO } from './beats/opening';
import { holders } from './beats/holders';
import { referral } from './beats/referral';
import { cost } from './beats/cost';
import { speed } from './beats/speed';
import { counter } from './beats/counter';
import { ending } from './beats/ending';
import { memoryCards } from './cards';
import { SERIF, SERIF_SC, setAnisotropy } from './floortype';
import { slabGrid } from './ground';
import { captions, scrollClock } from './scroll';
import { prepareWash } from './solid';
import { frameAt, holdKeys, Stage } from './stage';
import { eio, lerp, seg } from './ease';

function webglProblem(): string | null {
  const gl = document.createElement('canvas').getContext('webgl2');
  if (!gl) return 'the browser returned no WebGL2 context';
  gl.getExtension('WEBGL_lose_context')?.loseContext();
  return null;
}

async function loadFonts(): Promise<void> {
  const text = document.body.innerText + '往世乐土记住是谁的各归其主她知道七分之一的代价秒条记忆，一个文件同一个柜台';
  const faces = [`500 40px "${SERIF_SC}"`, `700 40px "${SERIF_SC}"`, `500 40px "${SERIF}"`, `600 40px "${SERIF}"`];
  const loaded = await Promise.all(faces.map((f) => document.fonts.load(f, text)));
  loaded.forEach((list, i) => {
    if (list.length === 0) throw new Error(`font ${faces[i]} did not load; floor type would fall back silently`);
  });
}

function wireCopyButtons(): void {
  for (const button of document.querySelectorAll<HTMLButtonElement>('[data-copy]')) {
    button.addEventListener('click', () => {
      const code = document.getElementById(button.dataset.copy ?? '');
      if (!code?.textContent) throw new Error(`copy button points at a missing code block "${button.dataset.copy}"`);
      navigator.clipboard.writeText(code.textContent).then(
        () => {
          button.textContent = 'Copied';
        },
        (err: unknown) => {
          button.textContent = 'Select and copy';
          console.warn('Elysian: clipboard refused the install command', err);
        },
      );
    });
  }
}

/** Caption height eases with the camera between beats, so the frame never jumps when a caption switches. */
function reserveKeys(beats: Beat[]): [number, number][] {
  const heights = beats.map((b) => {
    const cue = document.querySelector<HTMLElement>(`[data-beat="${b.id}"] .cue`);
    if (!cue) throw new Error(`section "${b.id}" has no .cue`);
    return cue.getBoundingClientRect().height + 28;
  });
  const keys: [number, number][] = [[beats[0].start, heights[0]]];
  for (let i = 1; i < beats.length; i++) keys.push([beats[i].start - 1.2, heights[i - 1]], [beats[i].start + 1.2, heights[i]]);
  return keys;
}

function reserveAt(keys: [number, number][], t: number): number {
  for (let i = keys.length - 1; i >= 0; i--) {
    if (t >= keys[i][0]) {
      const next = keys[i + 1];
      return next ? lerp(keys[i][1], next[1], eio(seg(t, keys[i][0], next[0]))) : keys[i][1];
    }
  }
  return keys[0][1];
}

async function boot(): Promise<void> {
  wireCopyButtons();
  const problem = webglProblem();
  if (problem) {
    console.warn(`Elysian: showing the text version, ${problem}.`);
    document.documentElement.classList.add('flat');
    document.getElementById('flat-note')?.removeAttribute('hidden');
    return;
  }
  const canvas = document.getElementById('world');
  if (!(canvas instanceof HTMLCanvasElement)) throw new Error('index.html has no <canvas id="world">');
  await loadFonts();
  const stage = new Stage(canvas);
  setAnisotropy(stage.anisotropy);
  document.documentElement.classList.add('scene');

  const world = new Group();
  stage.scene.add(world);
  world.add(slabGrid(-320, 40, -48, 48));
  const beats = [opening, holders, referral, cost, speed, counter, ending].map((build) => build(world));
  const keys = holdKeys(beats);
  prepareWash(world);

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let intro = reduced ? INTRO : 0;
  let reserve: [number, number][] = [];
  let lastT = Number.NaN;
  let dirty = true;
  const draw = (): void => {
    const scrolled = clock.time() - (INTRO - intro);
    const t = reduced ? showCaption(scrolled).settle : scrolled;
    if (t === lastT && !dirty) return;
    showCaption(t);
    lastT = t;
    dirty = false;
    for (const b of beats) b.update(t);
    stage.look(frameAt(keys, t), reserveAt(reserve, t));
    stage.render();
    canvas.dataset.t = t.toFixed(3);
  };
  const clock = scrollClock(beats, INTRO, T.end, !reduced, draw);
  const showCaption = captions(beats, clock);

  const resize = (): void => {
    stage.resize(window.innerWidth, window.innerHeight);
    reserve = reserveKeys(beats);
    dirty = true;
    draw();
  };
  window.addEventListener('resize', resize);
  resize();
  stage.renderer.compile(stage.scene, stage.camera);
  memoryCards(stage, beats.flatMap((b) => b.hover));

  if (!reduced) {
    const began = performance.now();
    const play = (now: number): void => {
      intro = Math.min(INTRO, (now - began) / 1000);
      draw();
      if (intro < INTRO) requestAnimationFrame(play);
    };
    requestAnimationFrame(play);
  }
}

void boot();
