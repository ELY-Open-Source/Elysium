import { ReactNode } from 'react';

export function Panel({ title, icon, children }: { title: string; icon: ReactNode; children: ReactNode }) {
  return (
    <section className="panel">
      <header className="panel-header">
        <span className="panel-icon">{icon}</span>
        <h2>{title}</h2>
      </header>
      {children}
    </section>
  );
}

export function Kpi({ icon, label, value, detail }: { icon: ReactNode; label: string; value: string; detail: string }) {
  return (
    <section className="kpi">
      <span className="panel-icon">{icon}</span>
      <div>
        <p>{label}</p>
        <strong>{value}</strong>
        <small>{detail}</small>
      </div>
    </section>
  );
}

export function Quiet({ children }: { children: ReactNode }) {
  return <div className="quiet-line">{children}</div>;
}

export function Pill({ state, children }: { state?: 'passed' | 'failed' | string; children: ReactNode }) {
  const tone = state === 'passed' || state === 'ready' || state === 'loaded' || state === 'current' ? ' passed' : '';
  return <span className={`proof-pill${tone}`}>{children}</span>;
}
