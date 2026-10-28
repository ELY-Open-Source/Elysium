# What speech is worth on the video questions

- commit: `3b87b77b7f73ceca0e43dfc07cc689a6365fd673`
- store measured: a copy of `bench/runs/dense_scale`; the source is never opened for write
- machine: 32 cpus, load [8.84, 22.74, 33.71]
- speech snapshot: `bench/models/faster-whisper-tiny` (the shipped default; its word error rate is in ASR.md)
- re-ingest: 129 files in 18848s
- speech atoms: 0 before → 28363 after (1419597 characters)

The only difference between the rows is the speech: same store, same files, same probes, same words-only path.

| asked | n | recall@10 | MRR | hit@10 | 95% lower | p50 s |
| --- | --- | --- | --- | --- | --- | --- |
| every video question (before) | 215 | 0.493 | 0.423 | 0.493 | 0.427 | 0.094 |
| the stratified probe sample (before) | 300 | 0.863 | 0.682 | 0.863 | 0.820 | 0.084 |
| every video question (after) | 215 | 0.516 | 0.396 | 0.516 | 0.450 | 0.156 |
| the stratified probe sample (after) | 300 | 0.789 | 0.618 | 0.790 | 0.740 | 0.166 |

Speech moved video recall@10 by +0.023 and the whole probe sample by -0.075.

Latency is read from the same pass and moves with machine load; the recall columns do not.
