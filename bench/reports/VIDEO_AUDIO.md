# What speech is worth on the video questions

- commit: `c1c9ad00586d81e40eb2bcad0cc1b7e13ade74b0`
- store measured: a copy of `bench/runs/dense_scale`; the source is never opened for write
- machine: 32 cpus, load [2.22, 5.22, 3.38]
- speech snapshot: `bench/models/faster-whisper-tiny` (the shipped default; its word error rate is in ASR.md)
- re-ingest: reused `bench/runs/video_audio_speech` (129 video sources), not re-timed in this run; that store was re-ingested before ingest kept provenance, so the copy's holders were re-stamped from the frozen corpus index (194336 atoms, 0 left without one)
- speech atoms: 0 before → 28363 after (1419597 characters)
- chance floor and the external counterpart for the same suite: `bench/reports/BASELINE_EXTERNAL.md`

The only difference between the rows is the speech: same store, same files, same queries, same words-only path.

| asked | n | recall@10 | MRR | hit@10 | 95% lower | p50 s |
| --- | --- | --- | --- | --- | --- | --- |
| every video question (before) | 215 | 0.493 | 0.423 | 0.493 | 0.427 | 0.102 |
| every answerable question (before) | 2928 | 0.848 | 0.692 | 0.850 | 0.837 | 0.083 |
| every video question (after) | 215 | 0.651 | 0.516 | 0.651 | 0.585 | 0.101 |
| every answerable question (after) | 2928 | 0.857 | 0.697 | 0.860 | 0.847 | 0.098 |

## recall@10 by modality, every answerable question

| stage | code | conversation | image | pdf | ui_screenshot | video |
| --- | --- | --- | --- | --- | --- | --- |
| before | 0.939 | 0.916 | 0.781 | 0.888 | 0.659 | 0.493 |
| after | 0.941 | 0.907 | 0.781 | 0.876 | 0.659 | 0.651 |

_Query counts: code 1237, conversation 150, image 240, pdf 766, ui_screenshot 320, video 215._

Speech moved video recall@10 by +0.158 and the whole answerable suite by +0.009.

Latency is read from the same pass and moves with machine load; the recall columns do not.
