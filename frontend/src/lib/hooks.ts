import { useCallback, useEffect, useState } from 'react';

import { errorMessage } from './format';

export interface Resource<T> {
  value: T | null;
  error: string | null;
}

/** Loads on mount, when `load` changes identity and when `revision` moves; a stale answer is dropped. */
export function useResource<T>(load: () => Promise<T>, revision = 0): Resource<T> {
  const [value, setValue] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let stale = false;
    load().then(
      (next) => {
        if (!stale) {
          setValue(next);
          setError(null);
        }
      },
      (err: unknown) => {
        if (!stale) {
          setError(errorMessage(err));
        }
      },
    );
    return () => {
      stale = true;
    };
  }, [load, revision]);

  return { value, error };
}

export interface Action {
  busy: string | null;
  error: string | null;
  notice: string | null;
  run: (label: string, work: () => Promise<string | void>) => Promise<void>;
}

/** One user action at a time: its label while it runs, then its notice or its error, never silence. */
export function useAction(): Action {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const run = useCallback(async (label: string, work: () => Promise<string | void>) => {
    setBusy(label);
    setError(null);
    setNotice(null);
    try {
      const said = await work();
      if (said) {
        setNotice(said);
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }, []);

  return { busy, error, notice, run };
}
