import '@fontsource-variable/newsreader/opsz.css';
import '@fontsource-variable/newsreader/opsz-italic.css';
import '@fontsource/noto-serif-sc/500.css';
import '@fontsource/noto-serif-sc/700.css';
import React from 'react';
import ReactDOM from 'react-dom/client';

import { App } from './App';
import './styles/base.css';
import './styles/sections.css';

const root = document.getElementById('root');
if (!root) {
  throw new Error('index.html has no #root to mount the console in');
}
ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
