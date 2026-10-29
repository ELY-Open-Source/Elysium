# The ranking on the described store

- commit: `f5c47d97f57322a556380dbff83a045cbf265385`
- store measured: a copy of `bench/runs/describe/after`, holders re-stamped; 47775 of 47775 pictures carry a description
- before: the `after` rows of `bench/reports/describe.json`, commit `3993644c65407f33213357eee1d1100636eaeb38`
- machine: 32 cpus, load [2.05, 2.29, 2.2]
- the external counterpart on the same suite: `bench/reports/BASELINE_EXTERNAL.md`

| split | n | chance (inside the asker's holder) | recall@10 before | recall@10 now | MRR now | 95% lower now |
| --- | --- | --- | --- | --- | --- | --- |
| dev | 991 | 0.5222 | 0.884 | 0.901 | 0.711 | 0.884 |
| test | 1937 | 0.5036 | 0.873 | 0.888 | 0.720 | 0.875 |
| whole | 2928 | 0.5099 | 0.877 | 0.893 | 0.717 | 0.883 |

## recall@10 by modality, dev

| row | code | conversation | image | pdf | ui_screenshot | video |
| --- | --- | --- | --- | --- | --- | --- |
| chance | 0.7143 | 0.2084 | 0.0110 | 0.5820 | 0.1514 | 0.5129 |
| before | 0.948 | 0.909 | 0.827 | 0.891 | 0.676 | 0.821 |
| now | 0.979 | 0.909 | 0.827 | 0.891 | 0.712 | 0.821 |
| 9B judge over the first 40 atoms | 0.984 | 0.965 | 0.880 | 0.894 | 0.730 | 0.875 |

## recall@10 by modality, test

| row | code | conversation | image | pdf | ui_screenshot | video |
| --- | --- | --- | --- | --- | --- | --- |
| chance | 0.6866 | 0.2104 | 0.0108 | 0.5751 | 0.1451 | 0.5003 |
| before | 0.917 | 0.917 | 0.827 | 0.884 | 0.732 | 0.818 |
| now | 0.954 | 0.906 | 0.827 | 0.884 | 0.737 | 0.818 |

## recall@10 by modality, whole

| row | code | conversation | image | pdf | ui_screenshot | video |
| --- | --- | --- | --- | --- | --- | --- |
| chance | 0.6962 | 0.2097 | 0.0109 | 0.5775 | 0.1473 | 0.5036 |
| before | 0.928 | 0.914 | 0.827 | 0.886 | 0.713 | 0.819 |
| now | 0.963 | 0.907 | 0.827 | 0.886 | 0.728 | 0.819 |

The judge on dev: recall@10 0.916 against 0.901 as shipped, MRR 0.795.

Latency moves with machine load and is kept in the JSON only; the recall columns do not.
