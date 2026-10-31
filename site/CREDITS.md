# Credits

## Isometric Picture Book style (MIT)

The look of this site follows the *Isometric Picture Book* style prompt and its Canvas-2D demo
from lemomo-ai/lemo-opuscar, released under the MIT License. The site is a new three.js
implementation; these pieces are adapted from the demo's `kit.js`:

- the three-tone shading rule `tri()` (lift toward `#FFF8EA`, drop toward `#5B4434`) and the palette
  (`src/palette.ts`);
- the proportions of the back-view person billboard (`src/person.ts`);
- the floor-type landing: about 0.14 s per character, scale 1.22 to 1, pale ghost to ink, and the
  phrase kinds B / A / s / n / e (`src/floortype.ts`).

```
MIT License

Copyright (c) lemomo-ai and the lemo-opuscar contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Fonts (SIL Open Font License 1.1)

- Noto Serif SC, Copyright 2012 Google Inc., from github.com/google/fonts `ofl/notoserifsc`.
- Newsreader, Copyright 2020 The Newsreader Project Authors, from github.com/google/fonts `ofl/newsreader`.

Both are subset to the characters this site uses by `scripts/subset_fonts.py`; the licence texts ship
beside the files in `public/fonts/`.
