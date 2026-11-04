# Voice-rule audio fixtures (FR-022, NFR-002)

This folder will hold the **3 consented voice-rule WAV fixtures** behind the sandbox's
"sample audio" buttons (judge step 6, spec section 4). It holds no audio yet.

| Fixture ID | Phrase (cached transcript) | Expected rule |
| --- | --- | --- |
| `vf_family_bin` | Tell me if anyone except family touches the bin after 9 PM | `po_bin`, touch, 21:00–06:00, `non_household` |
| `vf_strangers_gate` | Strangers only, not guests or deliveries: tell me if someone opens the side gate after dark | `po_side_gate`, touch, 17:30–06:00, `external_visitor_only` |
| `vf_named_gate` | Tell me if anyone except Sam touches the side gate after 10 PM | `po_side_gate`, touch, 22:00–06:00, `non_household`, plus the "Rules can't recognise individuals" notice |

## Who records them, and when

The owner records them in **T-07a** (daylight block): one consenting adult team member reads
each phrase once. Each file is a short WAV, **16 kHz, mono, 16-bit PCM**, under 30 s and 2 MB
(NFR-015), with no other voices, no names of real people other than the scripted "Sam", and no
background that could identify the house.

After recording:

1. Save them here as `vf_family_bin.wav`, `vf_strangers_gate.wav`, `vf_named_gate.wav`.
2. Add one entry per file to `config/audio_fixtures.json`: `id`, `file` (relative to
   `demo/voice/`), `sha256`
   (`python -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" demo/voice/vf_family_bin.wav`),
   the cached `transcript` (the phrase above, as Voice Transcribe returned it), a `label` and
   the consent note.
3. Run the `privacy-gate` skill. CI's repository-wide audio check fails on any audio file not
   listed there.

## Until then

The sample-audio buttons still work: `GET /api/voice/fixtures` lists the 3 fixture IDs with
their **cached transcripts** (from the bundle's `presets.json`, key `voice`) and no WAV URL,
and `POST /api/voice/transcribe {"fixture_id": ...}` returns the recorded transcript labelled
"recorded result". Once a WAV is listed here, the same button sends it live to Muse Voice
Transcribe 1.0 (behind the rate limit and the budget and judging caps), with the cached
transcript as the fallback.

Speech recorded in the browser is never written to disk or cached (NFR-002): only its
transcript is kept, keyed by the audio hash.
