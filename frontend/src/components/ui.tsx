import { ReactNode, useEffect, useRef, useState } from 'react';

import { sectionNamed } from '../lib/sections';

/** A word painted on the floor: it lies on the isometric ground and lands one character at a time. */
export function FloorWord({ text }: { text: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [landed, setLanded] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node) {
      throw new Error(`the floor word ${text} lost its node`);
    }
    const watcher = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setLanded(true);
        watcher.disconnect();
      }
    }, { threshold: 0.4 });
    watcher.observe(node);
    return () => watcher.disconnect();
  }, [text]);

  return (
    <span ref={ref} className={`floor floor-big${landed ? ' landed' : ''}`} aria-hidden="true">
      {Array.from(text).map((char, index) => (
        <span key={index} style={{ transitionDelay: `${index * 140}ms` }}>
          {char}
        </span>
      ))}
    </span>
  );
}

export function Section({ id, lede, children }: { id: string; lede: string; children: ReactNode }) {
  const { word, title } = sectionNamed(id);
  return (
    <section id={id} className="section" aria-labelledby={`${id}-title`}>
      <header className="section-head">
        <FloorWord text={word} />
        <h2 id={`${id}-title`}>{title}</h2>
        <p className="lede">{lede}</p>
      </header>
      <div className="section-body">{children}</div>
    </section>
  );
}

export function Notice({ text }: { text: string | null }) {
  return text ? <p className="notice" role="status">{text}</p> : null;
}

export function Fault({ text }: { text: string | null }) {
  return text ? <p className="fault" role="alert">{text}</p> : null;
}

export function Quiet({ children }: { children: ReactNode }) {
  return <p className="quiet">{children}</p>;
}

const GOOD_STATES = new Set(['passed', 'ready', 'loaded', 'current', 'mounted', 'bound']);

/** A state word; good states sit on subject green, everything else on paper. */
export function State({ value }: { value: string }) {
  return <span className={GOOD_STATES.has(value) ? 'state good' : 'state'}>{value}</span>;
}
