import { useState } from 'react';

import { readToken, writeToken } from '../api';
import { useActiveSection } from '../lib/scroll';
import { SECTIONS } from '../lib/sections';

const SECTION_IDS = SECTIONS.map((section) => section.id);

/** The bar that stays: the name, the way to each section, the write token and a refresh. */
export function Masthead({ onRefresh }: { onRefresh: () => void }) {
  const [token, setToken] = useState(readToken);
  const active = useActiveSection(SECTION_IDS);

  return (
    <header className="masthead">
      <a className="brand" href="#store">
        <span lang="zh">往世乐土</span> Elysian
      </a>
      <nav aria-label="sections">
        {SECTIONS.map((section) => (
          <a key={section.id} href={`#${section.id}`} className={active === section.id ? 'active' : undefined}>
            {section.title}
          </a>
        ))}
      </nav>
      <div className="masthead-tools">
        <input
          className="token"
          type="password"
          value={token}
          placeholder="Write token"
          aria-label="Write token"
          title="Writes need this when the server sets ELYSIUM_AUTH_TOKEN."
          onChange={(event) => {
            setToken(event.target.value);
            writeToken(event.target.value);
          }}
          onBlur={onRefresh}
        />
        <button type="button" className="link" onClick={onRefresh} title="Read the store again">
          Refresh
        </button>
      </div>
    </header>
  );
}
