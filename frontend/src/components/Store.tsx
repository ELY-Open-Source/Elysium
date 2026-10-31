import { Component, ReactNode, useCallback, useEffect, useRef, useState } from 'react';

import { errorMessage, formatNumber, humanize } from '../lib/format';
import { useResource } from '../lib/hooks';
import { loadStoreShape } from '../lib/shelves';
import { MODALITY_COLOURS } from '../scene/paint';
import { StoreScene } from '../scene/StoreScene';
import { Fault } from './ui';

interface Props {
  lit: string | null;
  revision: number;
  onPick: (holder: string) => void;
}

/** The store drawn as a room: one shelf per holder, a stack per kind of memory, the asked-about shelf lit. */
export function Store(props: Props) {
  return (
    <SceneBoundary>
      <StoreView {...props} />
    </SceneBoundary>
  );
}

function StoreView({ lit, revision, onPick }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const scene = useRef<StoreScene | null>(null);
  const [fault, setFault] = useState<string | null>(null);
  const loadShape = useCallback(() => loadStoreShape(lit), [lit]);
  const shape = useResource(loadShape, revision);

  useEffect(() => {
    const node = host.current;
    if (!node) {
      throw new Error('the store view lost its canvas host');
    }
    const made = new StoreScene(node, onPick);
    scene.current = made;
    const watcher = new ResizeObserver(() => made.resize());
    watcher.observe(node);
    return () => {
      watcher.disconnect();
      made.destroy();
      scene.current = null;
    };
  }, [onPick]);

  useEffect(() => {
    if (shape.value && scene.current) {
      scene.current.show(shape.value).catch((err: unknown) => setFault(errorMessage(err)));
    }
  }, [shape.value]);

  const value = shape.value;
  const rows = value ? (value.others ? [...value.shelves, value.others] : value.shelves) : [];
  return (
    <div className="store">
      <div ref={host} className="scene" data-testid="store-scene" data-lit={value?.lit ?? ''} />
      {value?.total === 0 && <p className="scene-empty">The store is empty.</p>}
      <Fault text={shape.error ?? fault} />
      {value && value.total > 0 && (
        <div className="legend">
          <p>
            {rows.map((row) => (
              <button
                key={row.holder || 'others'}
                type="button"
                className={row.holder && row.holder === value.lit ? 'link lit' : 'link'}
                onClick={() => onPick(row.holder)}
                title={row.holder ? `Show what ${row.holder} knows` : 'Show everyone'}
              >
                {row.holder || 'others'}
              </button>
            ))}
          </p>
          <p>
            {value.modalities.map((modality, column) => (
              <span key={modality} className="key">
                <i style={{ background: MODALITY_COLOURS[modality] }} />
                {humanize(modality)} {formatNumber(rows.reduce((sum, row) => sum + row.counts[column], 0))}
              </span>
            ))}
            <span className="key-note">Each box doubles the count.</span>
          </p>
        </div>
      )}
    </div>
  );
}

class SceneBoundary extends Component<{ children: ReactNode }, { fault: string | null }> {
  state: { fault: string | null } = { fault: null };

  static getDerivedStateFromError(error: unknown) {
    return { fault: `The store view could not draw: ${errorMessage(error)}` };
  }

  render() {
    return this.state.fault ? <Fault text={this.state.fault} /> : this.props.children;
  }
}
