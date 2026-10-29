# DENSE: the vector leg at corpus size (commit 80ffd9781)

- database: `bench/runs/dense_scale/data/ely_eye.sqlite`
- atoms: 165973, memories with words: 153857, vectors: 153857, pending: 0
- model: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, width 384
- build: 1444.9s for 153857 memories (106 per second)
- writing one memory into a full index: p50 508ms · p95 535ms over 50 writes
- the repair scan (`ely-eye build-dense-index`) over a full index: 1.3s, and it is not on the search path
- search p50 73.0ms · p95 75.7ms · max 85.6ms over 300 queries
- of which encoding the question: p50 11.3ms · p95 24.0ms
- against a brute-force scan: 0.998 of the top 10 over 40 probes (a returned atom counts when its true cosine is at least the k-th best, so ties cannot fail the check)
- bytes per stored vector: 1729 (266059776 bytes for 153857 vectors, dbstat page sizes over the vec0 shadow tables)
- machine: Linux 6.18.40.1-microsoft-standard-WSL2, 32 cores, 4 threads per query, load [3.53, 4.63, 4.85]

## One million vectors on this machine

- p50 475ms · p95 492ms
- vector table: 1.6 GiB
- first build: 156.5 minutes
- writing one vector: 3303ms — a vec0 delete by id scans the table, so this grows with the count too
- assumption: sqlite-vec 0.1.9 scans every vector, so latency and bytes grow linearly with the vector count; every row here is scaled by 1000000 / 153857 vectors, and the model, the machine and the thread budget stay the same

_Latency is wall time per search on the machine named above with the thread budget the benchmark pins; a run on a loaded machine is not comparable._
