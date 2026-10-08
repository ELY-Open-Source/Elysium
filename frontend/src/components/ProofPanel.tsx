import { GitBranch, Play, ShieldCheck } from 'lucide-react';
import { useEffect, useState } from 'react';

import { getLatestProofSuite, runHashHop, runProofSuite } from '../api';
import type { HashHopProof, ProofSuiteReport } from '../types';
import { errorMessage, formatNumber, shortHash } from '../lib/format';
import { Panel, Quiet } from './ui';

export function ProofPanel() {
  const [proofSuite, setProofSuite] = useState<ProofSuiteReport | null>(null);
  const [hashHop, setHashHop] = useState<HashHopProof | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function loadLatest() {
      try {
        const latest = await getLatestProofSuite().catch(() => null);
        if (!cancelled) {
          setProofSuite(latest);
        }
      } catch (err) {
        if (!cancelled) {
          setError(errorMessage(err));
        }
      }
    }
    void loadLatest();
    return () => {
      cancelled = true;
    };
  }, []);

  const passed = proofSuite?.checks.filter((check) => check.status === 'passed').length ?? 0;

  async function submitSuite() {
    setBusy('proof-suite');
    setError(null);
    try {
      setProofSuite(await runProofSuite());
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function submitHashHop(kind: 'text' | 'visual') {
    setBusy(`hashhop-${kind}`);
    setError(null);
    try {
      setHashHop(await runHashHop(kind, 2, kind === 'visual' ? 262144 : 1010000));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Panel title="PRD Proof Suite" icon={<ShieldCheck size={17} />}>
      <div className="proof-suite-header">
        <button className="action-button secondary" onClick={submitSuite} disabled={busy === 'proof-suite'}>
          <Play size={16} />
          Run Suite
        </button>
        <div className={proofSuite?.status === 'passed' ? 'proof-pill passed' : 'proof-pill'}>
          {proofSuite ? `${passed}/${proofSuite.checks.length} passed` : 'pending'}
        </div>
      </div>
      {proofSuite && (
        <div className="proof-list">
          {proofSuite.checks.map((check) => (
            <article className="proof-row" key={check.name}>
              <header>
                <strong>{check.name}</strong>
                <span className={check.status === 'passed' ? 'proof-status passed' : 'proof-status'}>{check.status}</span>
              </header>
              <p>{check.detail}</p>
              <small>{check.evidence[0]}</small>
            </article>
          ))}
          <div className="proof-box">
            <strong>{proofSuite.proof_id}</strong>
            <span>{proofSuite.status}</span>
            <small>{proofSuite.cartridge_id}</small>
            <small>{proofSuite.dna_after ?? proofSuite.dna_before}</small>
          </div>
        </div>
      )}
      {!proofSuite && <Quiet>Proof suite has not run yet</Quiet>}

      <div className="button-row">
        <button
          className="action-button secondary"
          onClick={() => submitHashHop('visual')}
          disabled={busy === 'hashhop-visual'}
        >
          <GitBranch size={15} />
          Visual 2-hop
        </button>
        <button
          className="action-button secondary"
          onClick={() => submitHashHop('text')}
          disabled={busy === 'hashhop-text'}
        >
          <GitBranch size={15} />
          Text 2-hop
        </button>
      </div>
      {hashHop && (
        <div className="proof-box">
          <strong>{shortHash(hashHop.proof_id)}</strong>
          <span>{hashHop.kind}</span>
          <span>{hashHop.hops} hops</span>
          <span>{formatNumber(hashHop.token_equivalent)} token eq</span>
          <small>{hashHop.expected_target_id}</small>
        </div>
      )}
      {error && <div className="error-line">{error}</div>}
    </Panel>
  );
}
