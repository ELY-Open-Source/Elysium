# BASELINE: what the product retrieves today

- generated 2026-10-06T20:42:42+00:00 at commit fc0698c2426c
- corpus 50278 sources, 10 queries (8 answerable)
- models: dense `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, rerank `BAAI/bge-reranker-base`

| arm | recall@1 | recall@5 | recall@10 | nDCG@10 | MRR | hit@10 (95% lower) | p50 s | p95 s |
|---|---|---|---|---|---|---|---|---|
| chance (random ranking) | 0.000 | 0.000 | 0.000 | - | - | - | - | - |
| bm25_only | 0.625 | 0.875 | 1.000 | 0.788 | 0.725 | 1.000 (0.676) | 0.881 | 1.207 |

## recall@10 by modality

| arm | pdf |
|---|---|
| bm25_only | 1.000 |

## unanswerable queries (44.8% of the suite)

- bm25_only: abstains on 0% of unanswerable queries, and puts a wrong-holder source on top for 100% of them

## reading

- recall counts a source as found only when it is the source a third party marked correct.
- abstention is the only honest number for unanswerable queries: a retriever that always
  returns ten results never says it does not know.
- chance is the floor any of these arms must beat; a number near chance is not a capability.
