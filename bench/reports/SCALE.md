# SCALE: the product's own search at corpus size

- commit: `dff5977ab638896cc8685c78ee41e5195fc0fbf2`
- database: bench/runs/scale/data/ely_eye.sqlite
- copied from the frozen baseline in 5.0s and migrated in 0.0s to schema 8; the baseline store itself is left untouched
- atoms: 165973, probes: 300 (code, image, pdf, ui_screenshot, video)
- dense embeddings: False
- p50 0.0717s · p95 0.2177s · max 0.7805s over 300 queries
- machine: Linux 6.18.40.1-microsoft-standard-WSL2, 32 cores, 4 threads per query, load [2.31, 3.72, 7.9]

The baseline recorded p50 20.16s on this corpus because the old search pulled every
atom into Python and rebuilt a BM25 index per query.

_Latency is wall time per search call on an idle machine with the thread budget the benchmark pins; a run on a loaded machine is not comparable._
