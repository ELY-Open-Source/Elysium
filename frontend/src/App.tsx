import { useCallback, useState } from 'react';

import { getAdapters, getStatus } from './api';
import { Cartridges } from './components/Cartridges';
import { Compiler } from './components/Compiler';
import { Ingest } from './components/Ingest';
import { Machine } from './components/Machine';
import { Masthead } from './components/Masthead';
import { Memory } from './components/Memory';
import { Overview } from './components/Overview';
import { Proofs } from './components/Proofs';
import { Fault } from './components/ui';
import { useResource } from './lib/hooks';
import { useSmoothScroll } from './lib/scroll';

const loadOverview = () => Promise.all([getStatus(), getAdapters()]);

export function App() {
  const [revision, setRevision] = useState(0);
  const [holder, setHolder] = useState('');
  const [lit, setLit] = useState<string | null>(null);
  const overview = useResource(loadOverview, revision);
  const [status, adapters] = overview.value ?? [null, null];
  const changed = useCallback(() => setRevision((count) => count + 1), []);
  const pick = useCallback((picked: string) => {
    setHolder(picked);
    setLit(picked || null);
    document.getElementById('memory')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, []);
  useSmoothScroll();

  return (
    <>
      <Masthead onRefresh={changed} />
      <main>
        <Fault text={overview.error} />
        <Overview status={status} adapters={adapters} lit={lit} revision={revision} onPick={pick} />
        <Memory holder={holder} onHolder={setHolder} onLit={setLit} revision={revision} onChanged={changed} />
        <Compiler onChanged={changed} />
        <Ingest onChanged={changed} />
        <Cartridges revision={revision} onChanged={changed} />
        <Machine status={status} adapters={adapters} revision={revision} />
        <Proofs />
      </main>
    </>
  );
}
