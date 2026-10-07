# BASELINE_EXTERNAL: memory counterparts on the same corpus

- generated 2026-10-07T19:16:08+00:00 at commit 3d792417cfd0
- 5308 queries (2928 answerable) against 50789 sources
- machine: 32 cores, load average 2.9 when the report was written
- extraction is lexical for both stores; Mem0's real add() and Zep's graph builder call a generator model, which this round does not have
- chance: random guessing scores recall@10 0.00020 over the whole corpus and 0.3686 inside one holder's memory (median 43 sources per holder); read each row against its own floor

| store | items | closed | recall@10 | hit@10 | hit@10 Wilson 95% lower | MRR | abstain (answerable) | abstain (unanswerable) | p50 s | p95 s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mem0_flat [holder scope] | 403859 | 0 | 0.866 | 0.867 | 0.855 | 0.629 | 0.000 | 0.000 | 0.083 | 0.105 |
| mem0_flat [whole corpus] | 403859 | 0 | 0.412 | 0.416 | 0.398 | 0.283 | 0.000 | 0.000 | 0.086 | 0.112 |
| zep_temporal [holder scope] | 403859 | 27072 | 0.866 | 0.867 | 0.854 | 0.627 | 0.000 | 0.058 | 0.084 | 0.113 |
| zep_temporal [whole corpus] | 403859 | 27072 | 0.429 | 0.433 | 0.415 | 0.297 | 0.000 | 0.000 | 0.094 | 0.121 |

n per modality: {"code": 2474, "conversation": 300, "image": 480, "pdf": 984, "ui_screenshot": 640, "video": 430}


`[holder scope]` answers only from the asking holder's memory; `[whole corpus]` searches every
holder's memory, which is what the product's arms are shown. The gap between the two rows is the
value of the holder boundary, not of a better ranker.

## mem0_flat [holder scope] by modality

| modality | n answerable | recall@10 | hit@10 | Wilson lower | MRR |
| --- | --- | --- | --- | --- | --- |
| code | 1237 | 0.952 | 0.952 | 0.939 | 0.695 |
| conversation | 150 | 0.993 | 1.000 | 0.975 | 0.927 |
| image | 240 | 0.646 | 0.654 | 0.592 | 0.505 |
| pdf | 766 | 0.916 | 0.916 | 0.895 | 0.692 |
| ui_screenshot | 320 | 0.622 | 0.622 | 0.568 | 0.330 |
| video | 215 | 0.716 | 0.716 | 0.653 | 0.396 |

## mem0_flat [whole corpus] by modality

| modality | n answerable | recall@10 | hit@10 | Wilson lower | MRR |
| --- | --- | --- | --- | --- | --- |
| code | 1237 | 0.349 | 0.349 | 0.323 | 0.216 |
| conversation | 150 | 0.500 | 0.573 | 0.493 | 0.373 |
| image | 240 | 0.525 | 0.533 | 0.470 | 0.362 |
| pdf | 766 | 0.683 | 0.683 | 0.649 | 0.515 |
| ui_screenshot | 320 | 0.075 | 0.075 | 0.051 | 0.033 |
| video | 215 | 0.116 | 0.116 | 0.080 | 0.069 |

## zep_temporal [holder scope] by modality

| modality | n answerable | recall@10 | hit@10 | Wilson lower | MRR |
| --- | --- | --- | --- | --- | --- |
| code | 1237 | 0.952 | 0.952 | 0.939 | 0.695 |
| conversation | 150 | 0.978 | 0.987 | 0.953 | 0.905 |
| image | 240 | 0.646 | 0.654 | 0.592 | 0.505 |
| pdf | 766 | 0.916 | 0.916 | 0.895 | 0.692 |
| ui_screenshot | 320 | 0.622 | 0.622 | 0.568 | 0.330 |
| video | 215 | 0.716 | 0.716 | 0.653 | 0.396 |

## zep_temporal [whole corpus] by modality

| modality | n answerable | recall@10 | hit@10 | Wilson lower | MRR |
| --- | --- | --- | --- | --- | --- |
| code | 1237 | 0.350 | 0.350 | 0.324 | 0.216 |
| conversation | 150 | 0.591 | 0.667 | 0.588 | 0.429 |
| image | 240 | 0.562 | 0.571 | 0.508 | 0.426 |
| pdf | 766 | 0.685 | 0.685 | 0.652 | 0.519 |
| ui_screenshot | 320 | 0.119 | 0.119 | 0.088 | 0.057 |
| video | 215 | 0.163 | 0.163 | 0.119 | 0.087 |
