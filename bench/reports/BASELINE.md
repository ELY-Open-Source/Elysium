# BASELINE: what the product retrieves today

- generated 2026-10-07T15:33:42+00:00 at commit b6503112a0c5
- corpus 50278 sources, 5308 queries (2928 answerable)
- models: dense `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, rerank `BAAI/bge-reranker-base`

| arm | recall@1 | recall@5 | recall@10 | nDCG@10 | MRR | hit@10 (95% lower) | p50 s | p95 s |
|---|---|---|---|---|---|---|---|---|
| chance (random ranking) | 0.000 | 0.000 | 0.000 | - | - | - | - | - |
| bm25_only | 0.313 | 0.465 | 0.519 | 0.415 | 0.383 | 0.524 (0.505) | 0.563 | 3.141 |
| dense_only | 0.227 | 0.363 | 0.424 | 0.321 | 0.290 | 0.429 (0.411) | 1.728 | 2.883 |
| graph_only | 0.000 | 0.001 | 0.001 | 0.000 | 0.000 | 0.001 (0.000) | 0.043 | 0.058 |
| no_rerank | 0.342 | 0.510 | 0.565 | 0.452 | 0.418 | 0.571 (0.553) | 2.404 | 5.169 |
| fusion_rerank | 0.236 | 0.391 | 0.453 | 0.341 | 0.309 | 0.459 (0.441) | 4.538 | 9.043 |

## recall@10 by modality

| arm | pdf | image | ui_screenshot | video | code | conversation |
|---|---|---|---|---|---|---|
| bm25_only | 0.704 | 0.637 | 0.322 | 0.126 | 0.518 | 0.368 |
| dense_only | 0.698 | 0.481 | 0.075 | 0.228 | 0.382 | 0.304 |
| graph_only | 0.000 | 0.000 | 0.000 | 0.000 | 0.002 | 0.000 |
| no_rerank | 0.742 | 0.669 | 0.297 | 0.153 | 0.592 | 0.447 |
| fusion_rerank | 0.253 | 0.692 | 0.300 | 0.088 | 0.629 | 0.486 |

## unanswerable queries (44.8% of the suite)

- bm25_only: abstains on 0% of unanswerable queries, and puts a wrong-holder source on top for 38% of them
- dense_only: abstains on 0% of unanswerable queries, and puts a wrong-holder source on top for 25% of them
- graph_only: abstains on 0% of unanswerable queries, and puts a wrong-holder source on top for 0% of them
- no_rerank: abstains on 0% of unanswerable queries, and puts a wrong-holder source on top for 40% of them
- fusion_rerank: abstains on 0% of unanswerable queries, and puts a wrong-holder source on top for 34% of them

## the unmodified product path

- RetrievalService.search: p50 20.16s, mean 20.67s, max 48.90s over 40 queries
- top-10 overlap with the fast BM25 path: 0.0%, identical order 0.0%
- its top-10 atoms cover only 7.6 distinct sources (min 1): the product ranks atoms and never diversifies, so ten slots fill with fragments of one document and the overlap with a source-level ranking is near zero

## latency vs corpus size

| sources | atoms | bm25_only p50/p95 s | dense_only p50/p95 s |
|---|---|---|---|
| 500 | 500 | 0.001/0.002 | 1.380/1.576 |
| 2000 | 2000 | 0.008/0.016 | 1.398/2.595 |
| 10000 | 10000 | 0.052/0.128 | 1.338/2.266 |
| 50000 | 165695 | 0.809/2.274 | 1.496/2.464 |

_latency only: a source prefix drops most gold sources, so recall at these sizes is meaningless_

## reading

- recall counts a source as found only when it is the source a third party marked correct.
- abstention is the only honest number for unanswerable queries: a retriever that always
  returns ten results never says it does not know.
- chance is the floor any of these arms must beat; a number near chance is not a capability.
