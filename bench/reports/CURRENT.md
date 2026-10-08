# CURRENT: what the product retrieves at this build

- generated 2026-10-08T20:17:12+00:00 at commit dff5977ab638
- measured store schema: v8
- corpus 50278 sources, 5308 queries (2928 answerable)
- models: dense `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, rerank `BAAI/bge-reranker-base`
- machine: 32 cores, 4 threads per query, load average 5.1 when the report was written

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

- bm25_only: abstains on 0% of unanswerable queries, and its top hit comes from the query's own holder for 38% of them; the rest are confident answers pulled out of somebody else's memory
- dense_only: abstains on 0% of unanswerable queries, and its top hit comes from the query's own holder for 25% of them; the rest are confident answers pulled out of somebody else's memory
- graph_only: abstains on 0% of unanswerable queries, and its top hit comes from the query's own holder for 0% of them; the rest are confident answers pulled out of somebody else's memory
- no_rerank: abstains on 0% of unanswerable queries, and its top hit comes from the query's own holder for 40% of them; the rest are confident answers pulled out of somebody else's memory
- fusion_rerank: abstains on 0% of unanswerable queries, and its top hit comes from the query's own holder for 34% of them; the rest are confident answers pulled out of somebody else's memory

## the product path, asked as its holder

- RetrievalService.search as the query's own holder: recall@10 0.832, MRR 0.683, hit@10 0.833 (95% lower 0.787) over n=300 answerable queries
- latency p50 0.074s, p95 0.146s, mean 0.079s, max 0.314s
- top-10 overlap with the fast BM25 path: 13.4%, identical order 0.0%
- its top-10 atoms cover 5.2 distinct sources on average (min 0): the product ranks atoms and never diversifies, so ten slots can fill with fragments of one document

## reading

- recall counts a source as found only when it is the source a third party marked correct.
- abstention is the only honest number for unanswerable queries: a retriever that always
  returns ten results never says it does not know.
- chance is the floor any of these arms must beat; a number near chance is not a capability.
