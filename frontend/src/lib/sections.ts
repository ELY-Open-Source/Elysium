export interface SectionName {
  id: string;
  word: string;
  title: string;
}

/** Every section of the console in page order: its anchor, its painted floor word, its English name. */
export const SECTIONS: SectionName[] = [
  { id: 'store', word: '乐土', title: 'Store' },
  { id: 'memory', word: '记忆', title: 'Memory' },
  { id: 'ask', word: '提问', title: 'Ask' },
  { id: 'ingest', word: '收录', title: 'Bring in' },
  { id: 'cartridges', word: '卡匣', title: 'Cartridges' },
  { id: 'machine', word: '机器', title: 'Machine' },
  { id: 'proofs', word: '验证', title: 'Proofs' },
];

export function sectionNamed(id: string): SectionName {
  const found = SECTIONS.find((section) => section.id === id);
  if (!found) {
    throw new Error(`no section is named ${id}`);
  }
  return found;
}
