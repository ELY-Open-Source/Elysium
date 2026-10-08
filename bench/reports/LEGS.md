# LEGS: what each retrieval leg is worth

- commit: `dff5977ab638896cc8685c78ee41e5195fc0fbf2`, schema v8
- store: bench/runs/leg_check/data/ely_eye.sqlite (a copy of bench/runs/dense_scale; the frozen baseline is never opened)
- 300 answerable queries, each asked as the holder the frozen set assigns it
- machine: Linux 6.18.40.1-microsoft-standard-WSL2, 32 cores, 4 threads per query, load [25.51, 9.62, 5.7]

Recall is scored on the first ten **sources** after atoms are collapsed to their source
by first hit, which is how every other arm in this repo is scored.

| leg configuration | atoms asked | recall@10 | MRR | hit@10 | 95% lower | p50 ms | p95 ms | distinct sources |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| words only | 10 | 0.832 | 0.683 | 0.833 | 0.787 | 65.5 | 134.9 | 4.0 |
| words only (the configured 24) | 24 | 0.848 | 0.688 | 0.850 | 0.805 | 72.5 | 155.9 | 6.0 |
| words only, wider page | 30 | 0.855 | 0.690 | 0.857 | 0.812 | 64.7 | 129.7 | 6.0 |
| + dense leg | 10 | 0.845 | 0.663 | 0.847 | 0.802 | 472.9 | 577.5 | 5.0 |
| + dense leg, wider page | 30 | 0.858 | 0.669 | 0.860 | 0.816 | 413.7 | 525.8 | 7.0 |
| + picture leg | 10 | 0.815 | 0.553 | 0.817 | 0.769 | 132.5 | 271.3 | 8.0 |
| + picture leg, wider page | 30 | 0.825 | 0.551 | 0.827 | 0.780 | 162.8 | 283.7 | 20.0 |

## recall@10 by modality

| leg configuration | code | image | pdf | ui_screenshot | video |
| --- | --- | --- | --- | --- | --- |
| words only | 0.953 | 0.750 | 0.849 | 0.583 | 0.583 |
| words only (the configured 24) | 0.953 | 0.750 | 0.895 | 0.583 | 0.625 |
| words only, wider page | 0.953 | 0.750 | 0.919 | 0.583 | 0.625 |
| + dense leg | 0.938 | 0.750 | 0.884 | 0.639 | 0.625 |
| + dense leg, wider page | 0.938 | 0.750 | 0.919 | 0.639 | 0.667 |
| + picture leg | 0.930 | 0.750 | 0.849 | 0.528 | 0.583 |
| + picture leg, wider page | 0.898 | 0.750 | 0.907 | 0.500 | 0.708 |

_Query counts per modality: code 128, image 26, pdf 86, ui_screenshot 36, video 24._

The picture leg is not a switch this harness flips per row: the product runs it only when the sparse page comes back thin, so these rows measure the product with the leg available, not a forced always-on fusion.

_Latency is wall time per search on the machine named above with the thread budget the benchmark pins; a run on a loaded machine is not comparable._
