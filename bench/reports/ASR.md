# ASR: what the speech reader hears (commit 03ca35763)

- generated 2026-10-08T01:05:45+00:00
- model: Systran/faster-whisper-tiny (cpu int8), model.bin sha256 dcb76c6586fc06cb…
- reference: Video-MME community subtitles (third-party captions, not verbatim transcripts)
- machine: {'system': 'Linux', 'release': '6.18.40.1-microsoft-standard-WSL2', 'cpus': 32, 'threads_per_query': 4, 'load_average_1_5_15': [1.84, 1.85, 6.99]}

| video | audio s | transcribe s | ×realtime | speech atoms | words | WER | mean word confidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0IdYJGBmguM | 88.9 | 1.73 | 51.3 | 31 | 218 | 0.179 | 0.879 |
| 1q-5IIyZL20 | 99.9 | 1.94 | 51.6 | 32 | 300 | 0.28 | 0.83 |
| 1tidNDIpKSY | 21.7 | 1.34 | 16.1 | 3 | 32 | 0.278 | 0.852 |

Over 3 videos and 210.5 seconds of audio: word error rate **0.242** against captions nobody here wrote, 66 speech atoms carrying 550 word-level timestamps, 0 words out of order and 0 starting before their own segment.

A caption track drops words a transcript keeps, so this WER is an upper bound on the model's real error. The point of the run is not the number: before this change an audio file produced no memory at all, and every word here now has an instant attached to it.
