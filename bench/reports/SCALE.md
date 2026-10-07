# SCALE: the product's own search at corpus size

- database: bench/runs/baseline/data/ely_eye.sqlite
- atoms: 165973, probes: 300 (code, image, pdf, ui_screenshot, video)
- dense embeddings: False
- opening the store (migrations included): 0.000s
- p50 0.0570s · p95 0.1383s · max 0.5395s over 300 queries
- machine: Linux 6.18.40.1-microsoft-standard-WSL2, 32 cores, 4 threads per query, load [1.77, 1.62, 1.64]

_Latency is wall time per search call on an idle machine with the thread budget the benchmark pins; a run on a loaded machine is not comparable._
