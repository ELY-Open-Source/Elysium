import type { Group } from 'three';
import { T, X, type Beat } from '../beat';
import { FloorPhrase, type Phrase } from '../floortype';
import { C } from '../palette';
import { dashes, strip, type Strip } from '../solid';
import { seg, ss } from '../ease';
import { cover, fit } from '../stage';

// bench/reports/LIVE.md: 110 questions, the same local Qwen3.5-9B as every system's LLM.
const ARMS = [
  { name: 'Elysian + 9B judge', recall: 0.909, tokens: 32_365, bar: C.accent, cost: C.accentLt, value: 'nsa', big: 'na' },
  { name: 'Elysian', recall: 0.864, tokens: 23_087, bar: C.green, cost: C.greenLt, value: 'ns', big: 'n' },
  { name: 'Mem0 raw', recall: 0.891, tokens: 23_087, bar: C.soft, cost: '#CFC4AF', value: 'ns', big: 'n' },
  { name: 'Mem0 + LLM extraction', recall: 0.718, tokens: 228_116, bar: C.soft, cost: '#CFC4AF', value: 'ns', big: 'n' },
  { name: 'Mem0 + LLM rerank', recall: 0.718, tokens: 233_436, bar: C.soft, cost: '#CFC4AF', value: 'ns', big: 'n' },
] as const;
const CHANCE = 0.591;
const RECALL_M = 10;
const DECADE_M = 4.5;
const FLOOR_TOKENS = 10_000;
const AXIS_Y = 4.4;

const rowY = (r: number): number => -3.2 + 1.6 * r;
const costM = (tokens: number): number => DECADE_M * Math.log10(tokens / FLOOR_TOKENS);
const thousands = (n: number): string => n.toLocaleString('en-US');

/**
 * Bars on the ground: recall grows up-right from the names, 9B tokens on a log axis grow down-left.
 * A portrait screen cannot hold the small labels legibly, so it shows the recall half with large
 * values and leaves names and token counts to the caption's table.
 */
export function cost(root: Group): Beat {
  const t0 = T.cost;
  const xc = X.cost + 1;
  const xr = xc - 3;
  const xk = xc + 2.4;
  const grow = t0 + 2.4;
  const wide: FloorPhrase[] = [];
  const narrow: FloorPhrase[] = [];
  const say = (p: Phrase, set = wide): void => {
    const f = new FloorPhrase({ step: 0.05, ...p });
    set.push(f);
    root.add(f.node);
  };

  const bars: { s: Strip; at: number }[] = [];
  const spends: Strip[] = [];
  ARMS.forEach((arm, r) => {
    const y = rowY(r);
    const at = grow + r * 0.22;
    const recall = strip(xr, y, 'x', -RECALL_M * arm.recall, 0.9, 0.006, arm.bar);
    const spend = strip(xk, y, 'x', costM(arm.tokens), 0.9, 0.006, arm.cost);
    root.add(recall.mesh, spend.mesh);
    bars.push({ s: recall, at }, { s: spend, at });
    spends.push(spend);
    say({ x: xr + 0.35, y: y + 0.3, t0: at, align: 'end', lines: [[[arm.name, 'es']]] });
    say({ x: xr - RECALL_M * arm.recall - 0.35, y: y + 0.4, t0: at + 1.2, lines: [[[arm.recall.toFixed(3), arm.value]]] });
    say({ x: xr - RECALL_M * arm.recall - 0.3, y: y + 0.66, t0: at + 1.2, lines: [[[arm.recall.toFixed(3), arm.big]]] }, narrow);
    say({ x: xk + costM(arm.tokens) + 0.35, y: y + 0.3, t0: at + 1.2, align: 'end', lines: [[[thousands(arm.tokens), 'en']]] });
  });
  say({ x: xr - RECALL_M * 0.718 - 2.7, y: rowY(4) + 0.3, t0: grow + 2.6, lines: [[['p50 15.6 s', 'en']]] });

  const costAxis: Strip[] = [strip(xk, AXIS_Y, 'x', costM(300_000), 0.05, 0.006, C.soft)];
  const axes: Strip[] = [strip(xr, AXIS_Y, 'x', -RECALL_M, 0.05, 0.006, C.soft)];
  for (const [tokens, label] of [[10_000, '10k'], [30_000, '30k'], [100_000, '100k'], [300_000, '300k']] as const) {
    costAxis.push(strip(xk + costM(tokens), AXIS_Y, 'y', 0.3, 0.05, 0.006, C.soft));
    say({ x: xk + costM(tokens), y: AXIS_Y + 1.0, t0: grow + 0.4, align: 'middle', lines: [[[label, 'en']]] });
  }
  for (const v of [0, 0.5, 1]) {
    axes.push(strip(xr - RECALL_M * v, AXIS_Y, 'y', 0.3, 0.05, 0.006, C.soft));
    say({ x: xr - RECALL_M * v, y: AXIS_Y + 1.0, t0: grow + 0.4, align: 'middle', lines: [[[v.toFixed(1), 'en']]] });
  }
  [...axes, ...costAxis].forEach((a) => root.add(a.mesh));
  say({ x: xk + costM(40_000), y: AXIS_Y + 2.0, t0: grow + 0.8, align: 'middle', lines: [[['9B tokens per question, log scale', 'en']]] });
  say({ x: xr - RECALL_M * 0.5, y: AXIS_Y + 2.0, t0: grow + 0.8, align: 'middle', lines: [[['recall@10, 110 questions', 'en']]] });

  const chanceX = xr - RECALL_M * CHANCE;
  const chance = dashes([[chanceX, -4.0], [chanceX, AXIS_Y]], 0.007, C.ink, 0.05);
  root.add(chance.node);
  say({ x: chanceX, y: -4.3, t0: grow + 1.6, align: 'middle', lines: [[[`chance ${CHANCE}`, 'en']]] });

  const judgeTip = xk + costM(ARMS[0].tokens);
  const mem0Tip = xk + costM(ARMS[3].tokens);
  const bracket = dashes([[judgeTip, AXIS_Y - 0.1], [judgeTip, AXIS_Y - 0.5], [mem0Tip, AXIS_Y - 0.5], [mem0Tip, AXIS_Y - 0.1]], 0.007, C.ink);
  root.add(bracket.node);

  const phrase = new FloorPhrase({ x: xc + 3.2, y: 9.4, t0: t0 + 7.6, lines: [[['七', 'A'], ['分之一', 'B'], ['的代价', 's']]] });
  root.add(phrase.node);

  return {
    id: 'cost',
    start: t0,
    settle: t0 + 10.4,
    hover: [],
    keys: [
      [t0 + 2.0, fit(xc - 16, xc + 11.5, -5.0, 9.8, 0, 1.06)],
      [t0 + 10, fit(xc - 16, xc + 11.5, -5.0, 9.8, 0, 1.02)],
    ],
    portrait: [
      [t0 + 2.0, fit(...cover(...narrow.map((n) => n.box), phrase.box, [xr - RECALL_M * 0.6, xr + 0.4, -3.8, 3.8]), 0, 1.06)],
      [t0 + 10, fit(...cover(...narrow.map((n) => n.box), phrase.box, [xr - RECALL_M * 0.6, xr + 0.4, -3.8, 3.8]), 0, 1.03)],
    ],
    update(t, portrait) {
      for (const b of bars) b.s.grow(ss(seg(t, b.at, b.at + 1.3)));
      const axis = ss(seg(t, grow - 0.4, grow + 0.6));
      for (const a of [...axes, ...costAxis]) a.grow(axis);
      for (const s of [...spends, ...costAxis]) s.mesh.visible &&= !portrait;
      chance.reveal(ss(seg(t, grow + 1.2, grow + 2.0)));
      bracket.reveal(ss(seg(t, t0 + 6.4, t0 + 7.4)));
      bracket.node.visible = !portrait;
      for (const p of wide) {
        p.node.visible = !portrait;
        p.update(t);
      }
      for (const p of narrow) {
        p.node.visible = portrait;
        p.update(t);
      }
      phrase.update(t);
    },
  };
}
