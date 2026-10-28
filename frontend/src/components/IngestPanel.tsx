import { FileSearch, Upload } from 'lucide-react';
import { FormEvent, useState } from 'react';

import { ingestPath, uploadFiles } from '../api';
import type { IngestResponse } from '../types';
import { errorMessage, formatNumber } from '../lib/format';
import { Panel } from './ui';

export function IngestPanel({ onChanged }: { onChanged: () => void }) {
  const [path, setPath] = useState('');
  const [cartridgeName, setCartridgeName] = useState('elysium-cartridge');
  const [files, setFiles] = useState<File[]>([]);
  const [lastIngest, setLastIngest] = useState<IngestResponse | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(label: string, work: () => Promise<IngestResponse>) {
    setBusy(label);
    setError(null);
    try {
      setLastIngest(await work());
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  function submitPath(event: FormEvent) {
    event.preventDefault();
    void run('ingest-path', () => ingestPath(path, cartridgeName));
  }

  function submitUpload(event: FormEvent) {
    event.preventDefault();
    void run('upload', () => uploadFiles(files, cartridgeName));
  }

  return (
    <Panel title="Input Stream" icon={<Upload size={17} />}>
      <form className="stack" onSubmit={submitPath}>
        <label>
          Cartridge
          <input value={cartridgeName} onChange={(event) => setCartridgeName(event.target.value)} />
        </label>
        <label>
          Local path
          <input value={path} onChange={(event) => setPath(event.target.value)} placeholder="/data/books" />
        </label>
        <button className="action-button" disabled={!path || busy === 'ingest-path'}>
          <FileSearch size={16} />
          Ingest Path
        </button>
      </form>
      <form className="stack" onSubmit={submitUpload}>
        <label>
          Files
          <input type="file" multiple onChange={(event) => setFiles(Array.from(event.target.files ?? []))} />
        </label>
        <button className="action-button secondary" disabled={files.length === 0 || busy === 'upload'}>
          <Upload size={16} />
          Upload Files
        </button>
      </form>
      {lastIngest && (
        <div className="metric-strip">
          <span>{lastIngest.source_count} sources</span>
          <span>{lastIngest.atom_count} atoms</span>
          <span>{formatNumber(lastIngest.token_equivalent)} tokens</span>
        </div>
      )}
      {error && <div className="error-line">{error}</div>}
    </Panel>
  );
}
