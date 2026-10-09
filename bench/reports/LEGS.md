# LEGS: what each retrieval leg is worth

- commit: `a52c10499b48f171db1ad40f20141acb34028200`, schema v10 — the copy arrives at v9 and the product migrates it when it opens, so every arm ran on v10
- store: bench/runs/leg_check/data/ely_eye.sqlite — a copy of bench/runs/dense_scale, which carries 153,857 dense vectors built by bench/dense_scale. The build sits outside the measured latency, and the frozen baseline itself holds no vectors, so a dense arm there would rank an empty index.
- 300 answerable queries, each asked as the holder the frozen set assigns it
- memory subset: every answerable conversation query (150) measured whole, because a 15-probe sample cannot separate six question types; the two tables further down use that subset, not the sample
- picture index: 53,668 atoms at 512 dimensions, 109,912,192 bytes, read from bench/runs/leg_check_index
- encoder speed: 18.8 pictures/s measured on 200 pictures, so the 53,668 pictures in that index cost about 47.5 minutes to encode
- machine: Linux 6.18.40.1-microsoft-standard-WSL2, 32 cores, 4 threads per query, load [17.23, 10.83, 6.53]

Recall is scored on the first ten **sources** after atoms are collapsed to their source
by first hit, which is how every other arm in this repo is scored.

| leg configuration | atoms asked | recall@10 | MRR | hit@10 | 95% lower | newest first | p50 ms | p95 ms | distinct sources |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| words only | 10 | 0.847 | 0.678 | 0.847 | 0.802 | 0.43 | 82.8 | 150.7 | 7.0 |
| words only (the configured 24) | 24 | 0.863 | 0.682 | 0.863 | 0.820 | 0.43 | 122.5 | 223.6 | 8.0 |
| words only, wider page | 30 | 0.873 | 0.686 | 0.873 | 0.831 | 0.43 | 83.7 | 158.0 | 8.0 |
| + dense leg | 10 | 0.860 | 0.669 | 0.860 | 0.816 | 0.43 | 713.3 | 833.0 | 7.0 |
| + dense leg, wider page | 30 | 0.873 | 0.675 | 0.873 | 0.831 | 0.43 | 579.0 | 756.6 | 9.0 |
| + picture leg | 10 | 0.817 | 0.565 | 0.817 | 0.769 | 0.43 | 145.2 | 337.7 | 9.0 |
| + picture leg, wider page | 30 | 0.848 | 0.538 | 0.850 | 0.805 | 0.43 | 219.5 | 360.4 | 22.0 |

## recall@10 by modality

| leg configuration | code | conversation | image | pdf | ui_screenshot | video |
| --- | --- | --- | --- | --- | --- | --- |
| words only | 0.945 | 1.000 | 0.720 | 0.833 | 0.818 | 0.409 |
| words only (the configured 24) | 0.945 | 1.000 | 0.720 | 0.885 | 0.818 | 0.455 |
| words only, wider page | 0.945 | 1.000 | 0.720 | 0.910 | 0.818 | 0.500 |
| + dense leg | 0.945 | 1.000 | 0.680 | 0.872 | 0.848 | 0.455 |
| + dense leg, wider page | 0.945 | 1.000 | 0.680 | 0.910 | 0.848 | 0.500 |
| + picture leg | 0.890 | 1.000 | 0.720 | 0.833 | 0.727 | 0.455 |
| + picture leg, wider page | 0.890 | 0.953 | 0.720 | 0.897 | 0.788 | 0.591 |

_Query counts per modality: code 127, conversation 15, image 25, pdf 78, ui_screenshot 33, video 22._

## recall@10 by question type, every memory query measured

| leg configuration | knowledge-update | multi-session | single-session-assistant | single-session-preference | single-session-user | temporal-reasoning |
| --- | --- | --- | --- | --- | --- | --- |
| words only | 1.000 | 0.857 | 1.000 | 0.800 | 0.960 | 0.879 |
| words only (the configured 24) | 1.000 | 0.857 | 1.000 | 0.800 | 0.960 | 0.879 |
| words only, wider page | 1.000 | 0.857 | 1.000 | 0.800 | 0.960 | 0.879 |
| + dense leg | 1.000 | 0.920 | 1.000 | 0.960 | 0.960 | 0.950 |
| + dense leg, wider page | 1.000 | 0.920 | 1.000 | 0.960 | 0.960 | 0.950 |
| + picture leg | 1.000 | 0.857 | 1.000 | 0.800 | 0.960 | 0.879 |
| + picture leg, wider page | 0.960 | 0.767 | 1.000 | 0.720 | 0.920 | 0.831 |

_Queries per type: knowledge-update 25, multi-session 25, single-session-assistant 25, single-session-preference 25, single-session-user 25, temporal-reasoning 25._

## the newest of the gold memories came back first

| leg configuration | knowledge-update | multi-session | temporal-reasoning |
| --- | --- | --- | --- |
| words only | 0.52 (25) | 0.46 (24) | 0.37 (19) |
| words only (the configured 24) | 0.52 (25) | 0.48 (25) | 0.37 (19) |
| words only, wider page | 0.52 (25) | 0.48 (25) | 0.37 (19) |
| + dense leg | 0.40 (25) | 0.46 (24) | 0.47 (19) |
| + dense leg, wider page | 0.40 (25) | 0.44 (25) | 0.47 (19) |
| + picture leg | 0.52 (25) | 0.46 (24) | 0.37 (19) |
| + picture leg, wider page | 0.52 (25) | 0.46 (24) | 0.37 (19) |

_Queries per type: knowledge-update 25, multi-session 24, temporal-reasoning 19._

recall@10 counts any gold memory, so a knowledge-update question can score 1.000 while the ranking still leads with the value the speaker has since replaced. The table above asks the sharper question: when the answer lives in several dated memories, is the newest one the first one returned? Only questions with at least two dated gold memories and at least one returned are counted.

The picture leg is not a switch this harness flips per row: the product runs it only when the sparse page comes back thin, so these rows measure the product with the leg available, not a forced always-on fusion.

_Latency is wall time per search on the machine named above with the thread budget the benchmark pins; a run on a loaded machine is not comparable._
