import { useState } from 'react';

import { getLatestProofSuite, runHashHop, runProofSuite } from '../api';
import { plural, shortHash } from '../lib/format';
import { useAction, useResource } from '../lib/hooks';
import type { HashHopProof, ProofSuiteReport } from '../types';
import { Fault, Quiet, Section, State } from './ui';

const HOPS = 2;
const HOP_TOKENS = { text: 1010000, visual: 262144 } as const;

/** The proof suite and the hash-hop probes: claims the store can check against itself. */
export function Proofs() {
  const latest = useResource(getLatestProofSuite);
  const [ran, setRan] = useState<ProofSuiteReport | null>(null);
  const [hashHop, setHashHop] = useState<HashHopProof | null>(null);
  const action = useAction();
  const suite = ran ?? latest.value;
  const passed = suite?.checks.filter((check) => check.status === 'passed').length;

  function hop(kind: 'text' | 'visual') {
    void action.run(`hop-${kind}`, async () => setHashHop(await runHashHop(kind, HOPS, HOP_TOKENS[kind])));
  }

  return (
    <Section id="proofs" lede="Claims the store checks against itself. Run them. Read what passed and what did not.">
      <div className="row">
        <button type="button" className="solid" onClick={() => void action.run('suite', async () => setRan(await runProofSuite()))} disabled={action.busy === 'suite'}>
          {action.busy === 'suite' ? 'Running' : 'Run the suite'}
        </button>
        <span className="tally" data-testid="suite-tally">
          {suite ? `${passed}/${suite.checks.length} passed` : latest.error ? 'unknown' : 'not run yet'}
        </span>
      </div>
      {suite ? (
        <div className="rows">
          {suite.checks.map((check) => (
            <article className="check" key={check.name}>
              <header>
                <h4>{check.name}</h4>
                <State value={check.status} />
              </header>
              <p>{check.detail}</p>
              {check.evidence.length > 0 && <p className="mono">{check.evidence[0]}</p>}
            </article>
          ))}
          <p className="facts-line mono">
            {suite.proof_id} · {suite.status} · {suite.cartridge_id} · dna {suite.dna_after ?? suite.dna_before ?? 'none'}
          </p>
        </div>
      ) : (
        <Quiet>The suite has not run on this store.</Quiet>
      )}
      <Fault text={latest.error} />

      <h3>Hash hops</h3>
      <div className="row">
        <button type="button" className="quiet-button" onClick={() => hop('visual')} disabled={action.busy === 'hop-visual'}>
          Visual 2-hop
        </button>
        <button type="button" className="quiet-button" onClick={() => hop('text')} disabled={action.busy === 'hop-text'}>
          Text 2-hop
        </button>
      </div>
      {hashHop && (
        <p className="facts-line mono">
          {shortHash(hashHop.proof_id)} · {hashHop.kind} · {hashHop.hops} hops · {plural(hashHop.token_equivalent, 'token')} · target{' '}
          {hashHop.expected_target_id}
        </p>
      )}
      <Fault text={action.error} />
    </Section>
  );
}
