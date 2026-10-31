import { atomImageUrl } from '../api';
import { formatStamp, humanize } from '../lib/format';
import type { EvidenceAtom } from '../types';

export interface AtomActions {
  busy: boolean;
  onReplace: (atom: EvidenceAtom) => void;
  onForget: (atom: EvidenceAtom) => void;
}

/** One memory: what it says, who holds it, in what setting, and how far to trust the reading. */
export function AtomRow({
  atom,
  meta,
  match = false,
  actions,
}: {
  atom: EvidenceAtom;
  meta: string;
  match?: boolean;
  actions: AtomActions;
}) {
  const when = atom.event_time ?? atom.ingested_at;
  return (
    <article className={match ? 'atom match' : 'atom'} data-atom={atom.atom_id}>
      {atom.image_ref && <img className="thumb" src={atomImageUrl(atom.atom_id)} alt={atom.atom_id} loading="lazy" />}
      <div className="atom-body">
        <p className="atom-meta">
          <span className="modality">{humanize(atom.modality)}</span>
          <span className="score">{meta}</span>
        </p>
        <p className="atom-text">{atom.text ? atom.text.slice(0, 220) : <em>No words on this atom.</em>}</p>
        <p className="atom-who">
          <strong>{atom.holder_id || 'no holder'}</strong> · {humanize(atom.origin)} ·{' '}
          {atom.scenario || 'no setting'} · {formatStamp(when)} · parser {atom.trust.parser.toFixed(2)}
          {atom.supersedes.length > 0 && <> · replaces {atom.supersedes.length}</>}
        </p>
      </div>
      <div className="atom-actions">
        <button type="button" className="link" title="Replace this memory" disabled={actions.busy} onClick={() => actions.onReplace(atom)}>
          Replace
        </button>
        <button type="button" className="link" title="Forget this memory" disabled={actions.busy} onClick={() => actions.onForget(atom)}>
          Forget
        </button>
      </div>
    </article>
  );
}
