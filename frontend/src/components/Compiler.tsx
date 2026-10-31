import { FormEvent, useState } from 'react';

import { askQuestion, atomImageUrl } from '../api';
import { humanize } from '../lib/format';
import { useAction } from '../lib/hooks';
import type { AnswerResponse, RuntimeProfile } from '../types';
import { Fault, Quiet, Section } from './ui';

const PROFILES: Array<{ id: RuntimeProfile; label: string }> = [
  { id: 'live_demo', label: 'Live demo' },
  { id: 'extreme_context', label: 'Extreme' },
  { id: 'library_100m', label: '100M library' },
  { id: 'research_theater', label: 'Research' },
];

/** Compiles the evidence for a question, asks the model, and shows what it cited. */
export function Compiler({ onChanged }: { onChanged: () => void }) {
  const [profile, setProfile] = useState<RuntimeProfile>('library_100m');
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<AnswerResponse | null>(null);
  const action = useAction();

  function submit(event: FormEvent) {
    event.preventDefault();
    void action.run('ask', async () => {
      setAnswer(await askQuestion(question, profile));
      onChanged();
    });
  }

  return (
    <Section id="ask" lede="Put a question to the model. It reads only what the store hands it, and names what it used.">
      <div className="choices" role="radiogroup" aria-label="Profile">
        {PROFILES.map((item) => (
          <button
            key={item.id}
            type="button"
            role="radio"
            aria-checked={profile === item.id}
            className={profile === item.id ? 'choice chosen' : 'choice'}
            onClick={() => setProfile(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>
      <form className="question" onSubmit={submit}>
        <label className="big-field">
          <span>Question</span>
          <textarea value={question} onChange={(event) => setQuestion(event.target.value)} rows={3} placeholder="what did we decide about the spare key" />
        </label>
        <button className="solid" disabled={!question || action.busy === 'ask'}>
          {action.busy === 'ask' ? 'Asking' : 'Ask'}
        </button>
      </form>
      <Fault text={action.error} />
      {answer ? (
        <div className="answer" data-testid="answer">
          <p className="answer-text">{answer.answer}</p>
          <p className="answer-meta">
            {answer.context.hits.length} hits · {Math.round(answer.verifier.citation_accuracy * 100)}% of citations hold ·{' '}
            {answer.runtime_backend}
          </p>
          <div className="evidence">
            {answer.context.hits.slice(0, 6).map((hit) => (
              <article key={hit.atom.atom_id} className="evidence-item">
                {hit.atom.image_ref && <img className="thumb" src={atomImageUrl(hit.atom.atom_id)} alt={hit.atom.atom_id} loading="lazy" />}
                <p className="atom-meta">
                  <span className="modality">{humanize(hit.atom.modality)}</span>
                  <span className="score">{hit.final_score.toFixed(3)}</span>
                </p>
                <p>{hit.atom.text.slice(0, 240)}</p>
                <p className="atom-who">
                  {hit.atom.source} · {hit.atom.holder_id || 'no holder'}
                </p>
              </article>
            ))}
          </div>
        </div>
      ) : (
        <Quiet>The evidence shows here after an answer.</Quiet>
      )}
    </Section>
  );
}
