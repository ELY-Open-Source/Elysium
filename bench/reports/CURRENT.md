# CURRENT: what the product retrieves at this build

- generated 2026-10-07T21:24:15+00:00 at commit dfc6cd4c2889
- measured store schema: v5
- corpus 50278 sources, 5308 queries (2928 answerable)
- models: dense `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, rerank `BAAI/bge-reranker-base`
- machine: 32 cores, 4 threads per query, load average 1.2 when the report was written

| arm | recall@1 | recall@5 | recall@10 | nDCG@10 | MRR | hit@10 (95% lower) | p50 s | p95 s |
|---|---|---|---|---|---|---|---|---|
| chance (random ranking) | 0.000 | 0.000 | 0.000 | - | - | - | - | - |

_re-timed on a stride sample with warm models; recall comes from the full pass (n=600 queries)_
| bm25_only | 0.313 | 0.465 | 0.519 | 0.415 | 0.383 | 0.524 (0.505) | 0.631 | 2.768 |
| dense_only | 0.227 | 0.363 | 0.424 | 0.321 | 0.290 | 0.429 (0.411) | 0.081 | 0.134 |
| graph_only | 0.000 | 0.001 | 0.001 | 0.000 | 0.000 | 0.001 (0.000) | 0.055 | 0.095 |
| no_rerank | 0.342 | 0.510 | 0.565 | 0.452 | 0.418 | 0.571 (0.553) | 0.643 | 2.786 |
| fusion_rerank | 0.236 | 0.391 | 0.453 | 0.341 | 0.309 | 0.459 (0.441) | 7.000 | 13.247 |

## recall@10 by modality

| arm | pdf | image | ui_screenshot | video | code | conversation |
|---|---|---|---|---|---|---|
| bm25_only | 0.704 | 0.637 | 0.322 | 0.126 | 0.518 | 0.368 |
| dense_only | 0.698 | 0.481 | 0.075 | 0.228 | 0.382 | 0.304 |
| graph_only | 0.000 | 0.000 | 0.000 | 0.000 | 0.002 | 0.000 |
| no_rerank | 0.742 | 0.669 | 0.297 | 0.153 | 0.592 | 0.447 |
| fusion_rerank | 0.253 | 0.692 | 0.300 | 0.088 | 0.629 | 0.486 |

## unanswerable queries (44.8% of the suite)

- bm25_only: abstains on 0% of unanswerable queries, and its top hit comes from the query's own holder for 38% of them; the rest are confident answers pulled out of somebody else's memory
- dense_only: abstains on 0% of unanswerable queries, and its top hit comes from the query's own holder for 25% of them; the rest are confident answers pulled out of somebody else's memory
- graph_only: abstains on 0% of unanswerable queries, and its top hit comes from the query's own holder for 0% of them; the rest are confident answers pulled out of somebody else's memory
- no_rerank: abstains on 0% of unanswerable queries, and its top hit comes from the query's own holder for 40% of them; the rest are confident answers pulled out of somebody else's memory
- fusion_rerank: abstains on 0% of unanswerable queries, and its top hit comes from the query's own holder for 34% of them; the rest are confident answers pulled out of somebody else's memory

## the unmodified product path

- RetrievalService.search: p50 0.68s, mean 1.08s, max 9.36s over 40 queries
- top-10 overlap with the fast BM25 path: 0.0%, identical order 0.0%
- its top-10 atoms cover only 7.7 distinct sources (min 1): the product ranks atoms and never diversifies, so ten slots fill with fragments of one document and the overlap with a source-level ranking is near zero

## latency vs corpus size

| sources | atoms | bm25_only p50/p95 s | dense_only p50/p95 s |
|---|---|---|---|
| 500 | 500 | 0.001/0.003 | 0.018/0.031 |
| 2000 | 2000 | 0.005/0.010 | 0.045/0.078 |
| 10000 | 10000 | 0.035/0.110 | 0.079/0.100 |
| 50000 | 165695 | 0.944/2.376 | 0.090/0.108 |

_latency only: a source prefix drops most gold sources, so recall at these sizes is meaningless_

_latency was measured at load average 1.2 on 32 cores; a busy machine inflates these figures, so read them as a ceiling_

## reading

- recall counts a source as found only when it is the source a third party marked correct.
- abstention is the only honest number for unanswerable queries: a retriever that always
  returns ten results never says it does not know.
- chance is the floor any of these arms must beat; a number near chance is not a capability.
