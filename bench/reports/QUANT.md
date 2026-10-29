# QUANT: what each vector encoding buys (commit 187f0e0ea)

- corpus: 165973 vectors, 384 dimensions, 200 probes, top 10
- machine: Linux 6.18.40.1-microsoft-standard-WSL2, 32 cores, 4 threads per query, load [2.46, 4.17, 4.58]
- probes are drawn from the corpus itself, so these arms are compared with each other, not quoted as retrieval quality; a hit is any returned atom whose true cosine is at least the 10-th best, because byte-identical atoms make the id set ambiguous

| arm | p50 ms | p95 ms | recall@10 |
| --- | --- | --- | --- |
| sqlite-vec float | 41.2 | 55.4 | 1.0 |
| sqlite-vec float + holder filter | 29.8 | 30.7 | 0.599 |
| sqlite-vec int8 | 35.5 | 42.2 | 0.977 |
| sqlite-vec int8 + holder filter | 22.3 | 28.1 | 0.595 |
| sqlite-vec bit | 2.6 | 2.8 | 0.728 |
| sqlite-vec bit + holder filter | 4.1 | 4.3 | 0.513 |
| numpy float32 scan (the truth) | 8.0 | 9.6 | 1.0 |
| numpy hamming (sign bit) | 18.9 | 19.8 | 0.011 |
| numpy float32 first 192 dims | 7.5 | 8.2 | 0.722 |
| numpy float32 first 128 dims | 7.9 | 8.9 | 0.57 |
| numpy float32 first 64 dims | 4.0 | 8.3 | 0.43 |
| bit coarse@200 -> float32 rerank in numpy | 23.7 | 24.7 | 0.983 |

| encoding | bytes per vector |
| --- | --- |
| float32 | 1536 |
| int8 | 384 |
| bit | 48 |

_Latency is wall time per query on the machine named above with the thread budget the benchmark pins; a run on a loaded machine is not comparable._
