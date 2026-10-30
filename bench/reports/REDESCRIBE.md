# Figures and screenshots described at 512 tokens

- commit: `79d1ea8825e1ff7c25a48b0b593d97c1dde136c5`
- store measured: a copy of `bench/runs/describe/after`, holders re-stamped; 21362 pictures (image, ui_screenshot) re-described at 512 tokens in 5997s by `Qwen/Qwen3.5-9B`; video frames keep their 192-token words
- before: `bench/reports/rank.json`, commit `5c43124f5473e2bbf82de91fbc8d9ecc4a776fa0`
- machine: 32 cpus, load [1.55, 10.29, 13.84]
- the external counterpart on the same suite: `bench/reports/BASELINE_EXTERNAL.md`

| split | n | chance (inside the asker's holder) | recall@10 192 tokens | recall@10 512 tokens | recall@10 192 tokens, reranked | recall@10 512 tokens, reranked |
| --- | --- | --- | --- | --- | --- | --- |
| dev | 991 | 0.5222 | 0.901 | 0.907 | 0.913 | 0.920 |
| test | 1937 | 0.5036 | 0.888 | 0.898 | 0.907 | 0.913 |
| whole | 2928 | 0.5099 | 0.893 | 0.901 | 0.909 | 0.916 |

| split | row | MRR | 95% lower |
| --- | --- | --- | --- |
| dev | 512 tokens | 0.727 | 0.891 |
| dev | 512 tokens, reranked | 0.799 | 0.904 |
| test | 512 tokens | 0.728 | 0.886 |
| test | 512 tokens, reranked | 0.810 | 0.901 |
| whole | 512 tokens | 0.728 | 0.892 |
| whole | 512 tokens, reranked | 0.806 | 0.907 |

## recall@10 by modality, dev

| row | code | conversation | image | pdf | ui_screenshot | video |
| --- | --- | --- | --- | --- | --- | --- |
| chance | 0.7143 | 0.2084 | 0.0110 | 0.5820 | 0.1514 | 0.5129 |
| 192 tokens | 0.979 | 0.909 | 0.827 | 0.891 | 0.712 | 0.821 |
| 512 tokens | 0.977 | 0.935 | 0.847 | 0.891 | 0.730 | 0.857 |
| 192 tokens, reranked | 0.984 | 0.968 | 0.867 | 0.894 | 0.739 | 0.821 |
| 512 tokens, reranked | 0.984 | 0.959 | 0.893 | 0.891 | 0.775 | 0.857 |

## recall@10 by modality, test

| row | code | conversation | image | pdf | ui_screenshot | video |
| --- | --- | --- | --- | --- | --- | --- |
| chance | 0.6866 | 0.2104 | 0.0108 | 0.5751 | 0.1451 | 0.5003 |
| 192 tokens | 0.954 | 0.906 | 0.827 | 0.884 | 0.737 | 0.818 |
| 512 tokens | 0.956 | 0.904 | 0.842 | 0.898 | 0.766 | 0.836 |
| 192 tokens, reranked | 0.974 | 0.936 | 0.861 | 0.884 | 0.789 | 0.818 |
| 512 tokens, reranked | 0.973 | 0.936 | 0.848 | 0.902 | 0.809 | 0.836 |

## recall@10 by modality, whole

| row | code | conversation | image | pdf | ui_screenshot | video |
| --- | --- | --- | --- | --- | --- | --- |
| chance | 0.6962 | 0.2097 | 0.0109 | 0.5775 | 0.1473 | 0.5036 |
| 192 tokens | 0.963 | 0.907 | 0.827 | 0.886 | 0.728 | 0.819 |
| 512 tokens | 0.963 | 0.916 | 0.844 | 0.896 | 0.753 | 0.842 |
| 192 tokens, reranked | 0.977 | 0.948 | 0.863 | 0.888 | 0.772 | 0.819 |
| 512 tokens, reranked | 0.977 | 0.945 | 0.863 | 0.898 | 0.800 | 0.842 |

Latency moves with machine load and is kept in the JSON only; the recall columns do not.
