import { ChevronLeft, ChevronRight, Database, Plus, Search, Trash2 } from 'lucide-react';
import { Dispatch, FormEvent, ReactNode, SetStateAction, useEffect, useState } from 'react';

import { atomImageUrl, forget, listAtoms, remember, search } from '../api';
import type { AtomPage, EvidenceAtom, SearchResult } from '../types';
import { errorMessage, formatAgo, formatNumber, formatStamp } from '../lib/format';
import { Panel, Quiet } from './ui';

const MODALITIES = ['text', 'code', 'image', 'audio', 'pdf_page', 'pdf_region', 'video_frame', 'ui_screenshot'];
const PAGE_SIZE = 12;

export function MemoryPanel({ onChanged }: { onChanged: () => void }) {
  const [query, setQuery] = useState('');
  const [holder, setHolder] = useState('');
  const [scenario, setScenario] = useState('');
  const [modality, setModality] = useState('');
  const [statement, setStatement] = useState('');
  const [result, setResult] = useState<SearchResult | null>(null);
  const [page, setPage] = useState<AtomPage | null>(null);
  const [history, setHistory] = useState<string[]>([]);
  const [cursor, setCursor] = useState<string | undefined>(undefined);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function loadBrowse(nextCursor?: string) {
    try {
      const next = await listAtoms({ limit: PAGE_SIZE, cursor: nextCursor, modality, holder });
      setPage(next);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  useEffect(() => {
    let cancelled = false;
    async function loadFirstPage() {
      try {
        const next = await listAtoms({ limit: PAGE_SIZE, modality, holder });
        if (!cancelled) {
          setPage(next);
        }
      } catch (err) {
        if (!cancelled) {
          setError(errorMessage(err));
        }
      }
    }
    void loadFirstPage();
    return () => {
      cancelled = true;
    };
  }, [modality, holder]);

  function changeFilter(apply: Dispatch<SetStateAction<string>>, value: string) {
    apply(value);
    setHistory([]);
    setCursor(undefined);
  }

  async function submitSearch(event: FormEvent) {
    event.preventDefault();
    if (!query) {
      return;
    }
    setBusy('search');
    setError(null);
    setNotice(null);
    try {
      setResult(await search(query, { holder, scenario, modality }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function submitRemember(event: FormEvent) {
    event.preventDefault();
    if (!statement) {
      return;
    }
    setBusy('remember');
    setError(null);
    try {
      await remember(statement, scenario);
      setNotice(`kept: ${statement.slice(0, 60)}`);
      setStatement('');
      await loadBrowse();
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function submitForget(atom: EvidenceAtom) {
    setBusy(`forget-${atom.atom_id}`);
    setError(null);
    try {
      const report = await forget(atom.atom_id, 'forgotten from the console');
      setNotice(
        `forgotten: ${report.atoms_deleted} atom${report.atoms_deleted === 1 ? '' : 's'}, ` +
          `${report.edges_deleted} links, ${report.cache_entries_cleared} cache entries` +
          (report.vector_index_dropped ? ', dense index dropped' : ''),
      );
      setResult(null);
      await loadBrowse();
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  function nextPage() {
    if (!page?.next_cursor) {
      return;
    }
    setHistory([...history, cursor ?? '']);
    setCursor(page.next_cursor);
    void loadBrowse(page.next_cursor);
  }

  function previousPage() {
    if (history.length === 0) {
      return;
    }
    const previous = history[history.length - 1];
    setHistory(history.slice(0, -1));
    setCursor(previous || undefined);
    void loadBrowse(previous || undefined);
  }

  return (
    <Panel title="Memory" icon={<Database size={17} />}>
      <form className="stack" onSubmit={submitSearch}>
        <label>
          Ask what someone knows
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="where are the keys" />
        </label>
        <div className="filter-row">
          <label>
            Holder
            <input
              value={holder}
              onChange={(event) => changeFilter(setHolder, event.target.value)}
              placeholder="any"
            />
          </label>
          <label>
            Scenario
            <input value={scenario} onChange={(event) => setScenario(event.target.value)} placeholder="any" />
          </label>
          <label>
            Modality
            <select value={modality} onChange={(event) => changeFilter(setModality, event.target.value)}>
              <option value="">any</option>
              {MODALITIES.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <button className="action-button" disabled={!query || busy === 'search'}>
          <Search size={16} />
          Search
        </button>
      </form>

      {result && (
        <div className="atom-list" data-testid="search-list">
          {result.status === 'no_match' && <Quiet>Nothing in the store answers “{result.query}”.</Quiet>}
          {result.hits.map((hit) => (
            <AtomRow
              key={hit.atom.atom_id}
              atom={hit.atom}
              meta={`${hit.final_score.toFixed(3)} · sparse ${hit.sparse_score.toFixed(2)} · visual ${hit.visual_score.toFixed(2)}`}
              busy={busy === `forget-${hit.atom.atom_id}`}
              onForget={() => submitForget(hit.atom)}
            />
          ))}
        </div>
      )}

      <form className="stack" onSubmit={submitRemember}>
        <label>
          Tell it something
          <input value={statement} onChange={(event) => setStatement(event.target.value)} placeholder="the spare glasses are in the hall drawer" />
        </label>
        <button className="action-button secondary" disabled={!statement || busy === 'remember'}>
          <Plus size={16} />
          Remember
        </button>
      </form>

      <div className="atom-list" data-testid="browse-list">
        {(page?.atoms ?? []).map((atom) => (
          <AtomRow
            key={atom.atom_id}
            atom={atom}
            meta={formatAgo(atom.event_time ?? atom.ingested_at)}
            busy={busy === `forget-${atom.atom_id}`}
            onForget={() => submitForget(atom)}
          />
        ))}
        {page && page.atoms.length === 0 && <Quiet>The store is empty.</Quiet>}
      </div>

      <div className="pager">
        <button className="icon-button" onClick={previousPage} disabled={history.length === 0} title="Previous page">
          <ChevronLeft size={16} />
        </button>
        <small>
          {page ? `${page.atoms.length} of ${formatNumber(page.total)} atoms` : 'loading'}
        </small>
        <button className="icon-button" onClick={nextPage} disabled={!page?.next_cursor} title="Next page">
          <ChevronRight size={16} />
        </button>
      </div>

      {notice && <div className="metric-strip"><span>{notice}</span></div>}
      {error && <div className="error-line">{error}</div>}
    </Panel>
  );
}

function AtomRow({
  atom,
  meta,
  busy,
  onForget,
}: {
  atom: EvidenceAtom;
  meta: string;
  busy: boolean;
  onForget: () => void;
}): ReactNode {
  return (
    <article className="atom-row" data-atom={atom.atom_id}>
      {atom.image_ref && <img className="thumb" src={atomImageUrl(atom.atom_id)} alt={atom.atom_id} loading="lazy" />}
      <div className="atom-body">
        <header>
          <span>{atom.modality}</span>
          <strong>{meta}</strong>
        </header>
        <p>{atom.text.slice(0, 200) || <em>no text on this atom</em>}</p>
        <small>
          {atom.holder_id || 'no holder'} · {atom.origin} · {atom.scenario || 'no scenario'} ·{' '}
          {formatStamp(atom.event_time ?? atom.ingested_at)} · parser {atom.trust.parser.toFixed(2)}
        </small>
      </div>
      <button className="icon-button" onClick={onForget} disabled={busy} title="Forget this memory">
        <Trash2 size={16} />
      </button>
    </article>
  );
}
