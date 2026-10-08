# ASR: what the speech reader hears (commit 10a39c512)

- generated 2026-10-08T02:37:10+00:00
- model: Systran/faster-whisper-tiny (cpu int8, 4 threads), model.bin sha256 dcb76c6586fc06cb…
- decode: word_timestamps=True, beam_size=1, temperature=(0.0,), condition_on_previous_text=False, vad_filter=False
- reference: Video-MME community subtitles: third-party captions, not verbatim transcripts
- machine: {'system': 'Linux', 'release': '6.18.40.1-microsoft-standard-WSL2', 'cpus': 32, 'threads_per_query': 4, 'load_average_1_5_15': [7.73, 2.66, 1.58]}

| video | audio s | transcribe s | ×realtime | reference words | words | WER | mean word confidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0IdYJGBmguM | 88.93 | 1.3 | 68.4 | 201 | 219 | 0.229 | 0.861 |
| 1q-5IIyZL20 | 109.18 | 1.28 | 85.4 | 296 | 313 | 0.253 | 0.821 |
| 1tidNDIpKSY | 60.07 | 0.54 | 111.2 | 36 | 31 | 0.222 | 0.852 |

Over 3 videos and 258.18 seconds of audio: word error rate **0.242** over 533 reference words (563 words heard), transcribed in 3.12 seconds.

Repeating the pass on the same machine gave WER 0.242 then 0.242; the transcripts were byte-identical. Decoding is greedy with no retry ladder, so a rerun is the same answer, not a new draw.

Ingested through the product path, the store holds 80 audio atoms from 3 sources carrying 563 word timestamps (0 out of order, 0 before their own segment) out of 133 atoms in total, checked on the words as stored rather than on the model's answer.

The captions are not a transcript, so this WER is not a bound in either direction: a caption that drops words also hides words the model dropped. The third row has only 36 reference words, where one word moves its rate by several points — read the denominators, not the decimals.
