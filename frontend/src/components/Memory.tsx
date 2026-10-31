import { FormEvent, useCallback, useState } from 'react';

import { forget, listAtoms, remember, search, supersede } from '../api';
import { describeForget, formatAgo, formatNumber, humanize } from '../lib/format';
import { useAction, useResource } from '../lib/hooks';
import { MODALITIES, type EvidenceAtom, type Modality, type SearchResult } from '../types';
import { AtomRow, type AtomActions } from './AtomRow';
import { Fault, Notice, Quiet, Section } from './ui';

/** Rows per browse page; scripts/verify-ui.mjs mirrors it to prove the pager against a known size. */
const PAGE_SIZE = 12;

interface Props {
  holder: string;
  onHolder: (holder: string) => void;
  onLit: (holder: string | null) => void;
  revision: number;
  onChanged: () => void;
}

export function Memory({ holder, onHolder, onLit, revision, onChanged }: Props) {
  const [query, setQuery] = useState('');
  const [scenario, setScenario] = useState('');
  const [modality, setModality] = useState<Modality | ''>('');
  const [statement, setStatement] = useState('');
  const [replacing, setReplacing] = useState<EvidenceAtom | null>(null);
  const [result, setResult] = useState<SearchResult | null>(null);
  const [paging, setPaging] = useState<{ filters: string; cursors: string[] }>({ filters: '', cursors: [] });
  const action = useAction();

  const filters = `${holder}\u0000${modality}`;
  const cursors = paging.filters === filters ? paging.cursors : [];
  const cursor = cursors.at(-1);
  const loadPage = useCallback(
    () => listAtoms({ limit: PAGE_SIZE, cursor, modality, holder }),
    [cursor, modality, holder],
  );
  const page = useResource(loadPage, revision);

  function afterWrite(said: string): string {
    setResult(null);
    onLit(null);
    onChanged();
    return said;
  }

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    void action.run('search', async () => {
      const found = await search(query, { holder, scenario, modality: modality || null });
      setResult(found);
      onLit(holder || found.hits.at(0)?.atom.holder_id || null);
    });
  }

  function submitStatement(event: FormEvent) {
    event.preventDefault();
    const target = replacing;
    void action.run('remember', async () => {
      if (target) {
        await supersede(target.atom_id, statement, scenario);
        setReplacing(null);
      } else {
        await remember(statement, scenario);
      }
      setStatement('');
      return afterWrite(`${target ? 'Replaced' : 'Kept'}: ${statement.slice(0, 60)}`);
    });
  }

  const actions: AtomActions = {
    busy: action.busy !== null,
    onReplace: (atom) => {
      setReplacing(atom);
      setStatement(atom.text);
      document.getElementById('remember-input')?.focus();
    },
    onForget: (atom) =>
      void action.run(`forget-${atom.atom_id}`, async () => {
        const report = await forget(atom.atom_id, 'forgotten from the console');
        if (replacing?.atom_id === atom.atom_id) {
          setReplacing(null);
        }
        return afterWrite(describeForget(report));
      }),
  };

  function turnPage(next: string[]) {
    setPaging({ filters, cursors: next });
  }

  return (
    <Section id="memory" lede="Ask what someone knows. Tell it something new. Take back what is wrong.">
      <form className="ask" onSubmit={submitSearch}>
        <label className="big-field">
          <span>Ask what someone knows</span>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="where are the keys" />
        </label>
        <div className="filters">
          <label>
            <span>Holder</span>
            <input value={holder} onChange={(event) => onHolder(event.target.value)} placeholder="anyone" />
          </label>
          <label>
            <span>Scenario</span>
            <input value={scenario} onChange={(event) => setScenario(event.target.value)} placeholder="any setting" />
          </label>
          <label>
            <span>Modality</span>
            <select value={modality} onChange={(event) => setModality(event.target.value as Modality | '')}>
              <option value="">any</option>
              {MODALITIES.map((name) => (
                <option key={name} value={name}>
                  {humanize(name)}
                </option>
              ))}
            </select>
          </label>
          <button className="solid" disabled={!query || action.busy === 'search'}>
            Search
          </button>
        </div>
      </form>

      {result && (
        <div className="atoms" data-testid="search-list">
          {result.status === 'no_match' && <Quiet>Nothing in the store answers “{result.query}”.</Quiet>}
          {result.hits.map((hit, index) => (
            <AtomRow
              key={hit.atom.atom_id}
              atom={hit.atom}
              match={index === 0}
              meta={
                `${hit.final_score.toFixed(3)} · sparse ${hit.sparse_score.toFixed(2)} · dense ${hit.dense_score.toFixed(2)}` +
                ` · visual ${hit.visual_score.toFixed(2)} · graph ${hit.graph_score.toFixed(2)}`
              }
              actions={actions}
            />
          ))}
        </div>
      )}

      <form className="tell" aria-label="Tell it something" onSubmit={submitStatement}>
        <label className="big-field">
          <span>{replacing ? 'Replace this memory' : 'Tell it something'}</span>
          <input
            id="remember-input"
            value={statement}
            onChange={(event) => setStatement(event.target.value)}
            placeholder="the spare glasses are in the hall drawer"
          />
        </label>
        {replacing && <p className="replacing">Was: “{replacing.text.slice(0, 120)}”</p>}
        <div className="row">
          <button className="solid" disabled={!statement || action.busy === 'remember'}>
            {replacing ? 'Replace' : 'Remember'}
          </button>
          {replacing && (
            <button type="button" className="link" onClick={() => setReplacing(null)}>
              Keep the old one
            </button>
          )}
          <span className="hint">{scenario ? `Kept in the setting “${scenario}”.` : 'Kept with no setting.'}</span>
        </div>
      </form>

      <Notice text={action.notice} />
      <Fault text={action.error} />

      <h3 className="shelf-title">The shelf, newest first</h3>
      <div className="atoms" data-testid="browse-list">
        {page.value?.atoms.map((atom) => (
          <AtomRow key={atom.atom_id} atom={atom} meta={formatAgo(atom.event_time ?? atom.ingested_at)} actions={actions} />
        ))}
        {page.value?.atoms.length === 0 && <Quiet>The store is empty.</Quiet>}
      </div>
      <Fault text={page.error} />
      <nav className="pager" aria-label="pages">
        <button type="button" className="link" title="Previous page" disabled={cursors.length === 0} onClick={() => turnPage(cursors.slice(0, -1))}>
          ← Newer
        </button>
        <span>{page.value ? `${page.value.atoms.length} of ${formatNumber(page.value.total)} atoms` : 'Loading.'}</span>
        <button
          type="button"
          className="link"
          title="Next page"
          disabled={!page.value?.next_cursor}
          onClick={() => page.value?.next_cursor && turnPage([...cursors, page.value.next_cursor])}
        >
          Older →
        </button>
      </nav>
    </Section>
  );
}
