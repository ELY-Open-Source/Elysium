# DENSE: the vector leg at corpus size (commit dff5977ab)

- database: `bench/runs/dense_scale/data/ely_eye.sqlite`
- atoms: 165973, memories with words: 153857, vectors: 153857, pending: 0
- model: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, width 384
- build: 1421.0s for 153857 memories (108 per second)
- writing one memory into a full index: p50 518ms · p95 543ms over 50 writes
- the repair scan (`ely-eye build-dense-index`) over a full index: 1.3s, and it is not on the search path
- search p50 75.6ms · p95 93.0ms · max 123.6ms over 300 queries
- of which encoding the question: p50 12.4ms · p95 25.8ms
- against a brute-force scan: 0.998 of the top 10 over 40 probes (a returned atom counts when its true cosine is at least the k-th best, so ties cannot fail the check)
- bytes per stored vector: 1729 (266059776 bytes for 153857 vectors, dbstat page sizes over the vec0 shadow tables)
- machine: Linux 6.18.40.1-microsoft-standard-WSL2, 32 cores, 4 threads per query, load [3.18, 4.58, 5.42]

## One million memories on this machine

- p50 455ms · p95 561ms
- vector table: 1.6 GiB
- first build: 153.9 minutes
- writing one memory: 3123ms — a vec0 delete by id scans the table, so this grows with the count too
- assumption: sqlite-vec 0.1.9 scans every vector, so latency and bytes grow linearly with the count; the model, the machine and the thread budget stay the same

_Latency is wall time per search on the machine named above with the thread budget the benchmark pins; a run on a loaded machine is not comparable._
