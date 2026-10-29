# What describing the pictures is worth

- commit: `3993644c65407f33213357eee1d1100636eaeb38`
- store measured: a copy of `bench/runs/video_audio_speech`, holders re-stamped from the frozen corpus index; the source is never opened for write
- machine: 32 cpus, load [1.54, 1.72, 1.78]
- descriptions: reused `bench/runs/describe/after`; 47775 of 47775 pictures carry one
- the external counterpart on the same suite: `bench/reports/BASELINE_EXTERNAL.md`

The only difference between the rows is the pictures' descriptions: same store, same queries, same words-only path.

| split | n | chance (inside the asker's holder) | recall@10 before | recall@10 after | MRR after | 95% lower after |
| --- | --- | --- | --- | --- | --- | --- |
| dev | 991 | 0.5222 | 0.865 | 0.884 | 0.696 | 0.866 |
| test | 1937 | 0.5036 | 0.853 | 0.873 | 0.710 | 0.859 |
| whole | 2928 | 0.5099 | 0.857 | 0.877 | 0.705 | 0.866 |

## recall@10 by modality, dev

| stage | code | conversation | image | pdf | ui_screenshot | video |
| --- | --- | --- | --- | --- | --- | --- |
| chance | 0.7143 | 0.2084 | 0.0110 | 0.5820 | 0.1514 | 0.5129 |
| before | 0.960 | 0.909 | 0.760 | 0.868 | 0.658 | 0.625 |
| after | 0.948 | 0.909 | 0.827 | 0.891 | 0.676 | 0.821 |

## recall@10 by modality, test

| stage | code | conversation | image | pdf | ui_screenshot | video |
| --- | --- | --- | --- | --- | --- | --- |
| chance | 0.6866 | 0.2104 | 0.0108 | 0.5751 | 0.1451 | 0.5003 |
| before | 0.931 | 0.906 | 0.791 | 0.880 | 0.660 | 0.660 |
| after | 0.917 | 0.917 | 0.827 | 0.884 | 0.732 | 0.818 |

## recall@10 by modality, whole

| stage | code | conversation | image | pdf | ui_screenshot | video |
| --- | --- | --- | --- | --- | --- | --- |
| chance | 0.6962 | 0.2097 | 0.0109 | 0.5775 | 0.1473 | 0.5036 |
| before | 0.941 | 0.907 | 0.781 | 0.876 | 0.659 | 0.651 |
| after | 0.928 | 0.914 | 0.827 | 0.886 | 0.713 | 0.819 |

Latency moves with machine load and is kept in the JSON only; the recall columns do not.
