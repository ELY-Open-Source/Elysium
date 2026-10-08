# LEGS: what each retrieval leg is worth

- commit: `71733d86d6d27d1f1ebb75205d5e0599f253f791`, schema v8
- store: bench/runs/leg_check/data/ely_eye.sqlite — a copy of bench/runs/dense_scale, which carries 153,857 dense vectors built by bench/dense_scale. The build sits outside the measured latency, and the frozen baseline itself holds no vectors, so a dense arm there would rank an empty index.
- 300 answerable queries, each asked as the holder the frozen set assigns it
- picture index: 53,668 atoms at 512 dimensions, 109,912,192 bytes, read from bench/runs/leg_check_index
- encoder speed: 16.8 pictures/s measured on 200 pictures, so the 53,668 pictures in that index cost about 53.3 minutes to encode
- machine: Linux 6.18.40.1-microsoft-standard-WSL2, 32 cores, 4 threads per query, load [22.19, 9.9, 6.39]

Recall is scored on the first ten **sources** after atoms are collapsed to their source
by first hit, which is how every other arm in this repo is scored.

| leg configuration | atoms asked | recall@10 | MRR | hit@10 | 95% lower | p50 ms | p95 ms | distinct sources |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| words only | 10 | 0.832 | 0.683 | 0.833 | 0.787 | 67.5 | 146.7 | 4.0 |
| words only (the configured 24) | 24 | 0.848 | 0.688 | 0.850 | 0.805 | 67.6 | 129.9 | 6.0 |
| words only, wider page | 30 | 0.855 | 0.690 | 0.857 | 0.812 | 72.0 | 156.0 | 6.0 |
| + dense leg | 10 | 0.845 | 0.663 | 0.847 | 0.802 | 474.8 | 579.1 | 5.0 |
| + dense leg, wider page | 30 | 0.858 | 0.669 | 0.860 | 0.816 | 416.0 | 543.4 | 7.0 |
| + picture leg | 10 | 0.815 | 0.553 | 0.817 | 0.769 | 138.1 | 303.6 | 8.0 |
| + picture leg, wider page | 30 | 0.825 | 0.551 | 0.827 | 0.780 | 166.7 | 314.2 | 20.0 |

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
