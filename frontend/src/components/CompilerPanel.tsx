import { Braces, Send } from 'lucide-react';
import { FormEvent, useState } from 'react';

import { askQuestion, atomImageUrl } from '../api';
import type { AnswerResponse, RuntimeProfile } from '../types';
import { errorMessage } from '../lib/format';
import { Panel, Quiet } from './ui';

const PROFILES: Array<{ id: RuntimeProfile; label: string }> = [
  { id: 'live_demo', label: 'Live Demo' },
  { id: 'extreme_context', label: 'Extreme' },
  { id: 'library_100m', label: '100M Library' },
  { id: 'research_theater', label: 'Research' },
];

export function CompilerPanel({ onChanged }: { onChanged: () => void }) {
  const [profile, setProfile] = useState<RuntimeProfile>('library_100m');
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<AnswerResponse | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submitQuestion(event: FormEvent) {
    event.preventDefault();
    if (!question) {
      return;
    }
    setBusy('chat');
    setError(null);
    try {
      setAnswer(await askQuestion(question, profile));
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Panel title="Context Compiler" icon={<Braces size={17} />}>
      <div className="segments">
        {PROFILES.map((item) => (
          <button
            key={item.id}
            className={profile === item.id ? 'segment active' : 'segment'}
            onClick={() => setProfile(item.id)}
            type="button"
          >
            {item.label}
          </button>
        ))}
      </div>
      <form className="stack" onSubmit={submitQuestion}>
        <textarea value={question} onChange={(event) => setQuestion(event.target.value)} rows={5} />
        <button className="action-button" disabled={!question || busy === 'chat'}>
          <Send size={16} />
          Ask
        </button>
      </form>
      {answer && (
        <div className="answer-box">
          <p>{answer.answer}</p>
          <div className="metric-strip">
            <span>{answer.context.hits.length} hits</span>
            <span>{Math.round(answer.verifier.citation_accuracy * 100)}% citations</span>
            <span>{answer.runtime_backend}</span>
          </div>
        </div>
      )}
      <div className="evidence-list">
        {(answer?.context.hits ?? []).slice(0, 6).map((hit) => (
          <article key={hit.atom.atom_id} className="evidence-row">
            <header>
              <span>{hit.atom.modality}</span>
              <strong>{hit.final_score.toFixed(3)}</strong>
            </header>
            {hit.atom.image_ref && (
              <img className="thumb" src={atomImageUrl(hit.atom.atom_id)} alt={hit.atom.atom_id} loading="lazy" />
            )}
            <p>{hit.atom.text.slice(0, 240)}</p>
            <small>
              {hit.atom.source} · {hit.atom.holder_id || 'no holder'}
            </small>
          </article>
        ))}
        {!answer && <Quiet>Evidence appears after a compiled answer</Quiet>}
      </div>
      {error && <div className="error-line">{error}</div>}
    </Panel>
  );
}
