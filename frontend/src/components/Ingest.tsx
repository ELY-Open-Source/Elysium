import { FormEvent, useState } from 'react';

import { ingestPath, uploadFiles } from '../api';
import { plural } from '../lib/format';
import { useAction } from '../lib/hooks';
import type { IngestResponse } from '../types';
import { Fault, Notice, Section } from './ui';

function describe(result: IngestResponse): string {
  const into = result.cartridge_id ? ` into ${result.cartridge_id}` : '';
  return `Read ${plural(result.source_count, 'source')}, ${plural(result.atom_count, 'atom')}, ${plural(result.token_equivalent, 'token')}${into}.`;
}

/** Brings files into the store, from a path on this machine or from the browser. */
export function Ingest({ onChanged }: { onChanged: () => void }) {
  const [path, setPath] = useState('');
  const [cartridgeName, setCartridgeName] = useState('elysian-cartridge');
  const [files, setFiles] = useState<File[]>([]);
  const action = useAction();

  function bringIn(label: string, work: () => Promise<IngestResponse>) {
    void action.run(label, async () => {
      const result = await work();
      onChanged();
      return describe(result);
    });
  }

  function submitPath(event: FormEvent) {
    event.preventDefault();
    bringIn('path', () => ingestPath(path, cartridgeName));
  }

  function submitFiles(event: FormEvent) {
    event.preventDefault();
    bringIn('upload', () => uploadFiles(files, cartridgeName));
  }

  return (
    <Section id="ingest" lede="Hand it files. Pages, pictures, sound and code become memories, and a cartridge if you name one.">
      <label className="field">
        <span>Cartridge</span>
        <input value={cartridgeName} onChange={(event) => setCartridgeName(event.target.value)} placeholder="no cartridge" />
      </label>
      <div className="two">
        <form onSubmit={submitPath}>
          <label className="field">
            <span>Local path</span>
            <input value={path} onChange={(event) => setPath(event.target.value)} placeholder="/data/books" />
          </label>
          <button className="solid" disabled={!path || action.busy === 'path'}>
            Ingest path
          </button>
        </form>
        <form onSubmit={submitFiles}>
          <label className="field">
            <span>Files</span>
            <input type="file" multiple onChange={(event) => setFiles(Array.from(event.target.files ?? []))} />
          </label>
          <button className="solid" disabled={files.length === 0 || action.busy === 'upload'}>
            Upload files
          </button>
        </form>
      </div>
      <Notice text={action.notice} />
      <Fault text={action.error} />
    </Section>
  );
}
