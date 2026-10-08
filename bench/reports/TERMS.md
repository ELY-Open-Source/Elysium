# TERMS: which query words are worth paying for

- commit: `dff5977ab638896cc8685c78ee41e5195fc0fbf2`
- store: bench/runs/term_sweep/data/ely_eye.sqlite (copied from the frozen baseline in 5.1s)
- 173 answerable probes, each asked as the holder the frozen set assigns it, ranked by the unmodified `RetrievalService`
- the bound the product ships is 0.05; the measured recall peak sits at 0.05
- machine: Linux 6.18.40.1-microsoft-standard-WSL2, 32 cores, 4 threads per query, load [2.32, 3.87, 8.09]

| bound | recall@10 | MRR | hit@10 | p50 ms | p95 ms | median distinct sources |
| --- | --- | --- | --- | --- | --- | --- |
| 0.200 | 0.792 | 0.629 | 0.792 | 420.3 | 1704.1 | 6 |
| 0.100 | 0.792 | 0.632 | 0.792 | 467.5 | 1747.5 | 6 |
| 0.050 **(shipped)** | 0.803 | 0.652 | 0.803 | 69.5 | 131.5 | 5 |
| 0.020 | 0.792 | 0.631 | 0.792 | 33.4 | 88.4 | 4 |
| 0.010 | 0.775 | 0.617 | 0.775 | 19.2 | 63.0 | 4 |
| 0.005 | 0.740 | 0.563 | 0.740 | 10.8 | 69.9 | 3 |

The bound is a share of the library: a word carried by more atoms than that is dropped from the OR query, because bm25 scores every row the query touches. It is relative to the corpus on purpose — a corpus of PDFs and a corpus of shell history disagree about which of their own words are noise.

_Latency is wall time per search on the machine named above with the thread budget the benchmark pins; a run on a loaded machine is not comparable._
