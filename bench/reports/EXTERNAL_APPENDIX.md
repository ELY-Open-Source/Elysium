# Appendix: what a real Mem0 run would cost, and why its numbers are not ours

`bench/counterpart.py` rebuilds the store-and-retrieve half of Mem0 and Zep inside this repo so the
comparison runs on one corpus, one machine, one scorer. The products themselves are not run here.
This appendix records what running them would take, and which of their published numbers can be
placed next to ours at all.

## what the counterpart reproduces, and what it does not

| behaviour | Mem0 / Zep paper | `bench/counterpart.py` |
|---|---|---|
| store granularity | LLM-extracted facts, deduplicated against existing facts | deterministic 400-character sentence chunks, deduplicated by `(holder, sha256(text))` |
| scope | `user_id` / `agent_id` / `run_id` | `holder` from the frozen corpus |
| invalidation | Zep closes an edge when a newer fact contradicts an older one | `supersede` closes the older item when a newer one in the same `(holder, subject)` group overlaps it by less than 0.5 |
| retrieval | dense + sparse + graph signals, `top_200` budget in the 2026 hosted stack | dense cosine over the same 384-dimensional embedder the ely-eye dense arm uses, `top_k=10` |
| scoring | LLM-as-a-judge on a generated answer | source-level recall@10 against frozen gold |

The extraction step is the part that cannot be made comparable: Mem0's `add()` calls an LLM per
ingest, so its store contents depend on the model, the prompt, and the sampling temperature. Running
it against this corpus would add an LLM to the ingest path and make the memory store itself
non-reproducible, while leaving the retrieval question untouched. That is why the reference point is
in-repo.

## published numbers worth keeping

From the Mem0 paper (arXiv 2504.19413v1, LOCOMO, overall LLM-as-a-judge score, mean ± std over 10 runs):

| system | overall judge score | tokens retrieved per query | search p50 / p95 (s) | total p50 / p95 (s) |
|---|---|---|---|---|
| full-context | 72.90 ± 0.19 | 26,031 | — | 9.870 / 17.117 |
| Mem0 (graph variant) | 68.44 ± 0.17 | 3,616 | 0.476 / 0.657 | 1.091 / 2.590 |
| Mem0 | 66.88 ± 0.15 | 1,764 | 0.148 / 0.200 | 0.708 / 1.440 |
| Zep | 65.99 ± 0.16 | 3,911 | 0.513 / 0.778 | 1.292 / 2.926 |
| best RAG configuration | 60.97 ± 0.20 | k × chunk size | 0.267 / 0.624 | 0.766 / 1.829 |
| LangMem | 58.10 ± 0.21 | 127 | 17.99 / 59.82 | 18.53 / 60.40 |
| A-Mem | 48.38 ± 0.15 | 2,520 | 0.668 / 1.485 | 1.410 / 4.374 |

Two things in that table matter more than the scores:

- **full-context wins the answer-quality column and loses the cost column.** 72.90 at 26,031 tokens
  per query, p95 17.1 s. Every memory system trades quality for cost. Any claim that a memory layer
  "beats the context window" has to say which column it means.
- **the store-construction cost is not in the table at all.** The paper tabulates search and answer
  latency, not `add()`. It reports separately that Zep's construction runs multiple asynchronous LLM
  calls, so retrieval immediately after an add often fails and improves hours later. A benchmark that
  scores retrieval only, on a store built in advance, hides that entirely.

Sources: arXiv 2504.19413v1 (table 2 and sections 4.1-4.5), the mem0 repository README's 2026
algorithm table (LoCoMo 92.5, LongMemEval 94.4, ~7.0k tokens, p50 0.88-1.09 s, single-pass retrieval
at a `top_200` budget, managed platform), and `docs.mem0.ai/core-concepts/memory-evaluation`.

## why these numbers cannot sit in our ablation table

1. Different metric. Their column is judge-scored answer correctness on 300 LOCOMO questions. Ours is
   recall@10 of the gold **source** over 2,928 answerable queries drawn from six third-party sets.
   A system can rank the right passage last and still answer correctly from a paraphrase.
2. Different budget. They retrieve `top_200` items; we score `top_k=10`.
3. Different hardware and model. Their run used a hosted production stack; ours is CPU-only with a
   384-dimensional multilingual MiniLM, no CUDA in this WSL image.
4. Different corpus age. LOCOMO has 10 dialogues; our conversation set is LongMemEval-cleaned with
   7,188 session files and 854 holders, and it also carries five non-conversational modalities that
   no memory product is evaluated on here.

The honest use of this appendix is the ordering it implies — full-context > memory systems > naive
RAG on answer quality, and the reverse on cost — plus the two cost columns the paper leaves out.
