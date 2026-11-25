# TB-303 Studio Mk III.2 · Validation

From the Studio folder, run `python -m unittest discover -s Tests -v` in the Python environment that runs the app. The Mk III.2 suite passed all **67 tests** on Linux with a virtual Tk display.

Mk III.2 adds 12 tests for photo registration, rotary gestures, panel BACK and TAP review, time entry, protected clear, the track/group detents, live controls, bar reset, quantized retuning, end-of-chain changes, short-buffer SDL output and external-clock LEDs. The photo comparison uses an actual Tk canvas at 1656 × 814: with overlays disabled its RGB pixels match the decoded supplied JPEG exactly. The accompanying PNG and GIF were captured from the running frontend. Audio tests used rendered samples and a simulated output device; no test implies calibration to the original hardware.


| Area | What was checked |
|---|---|
| English interface | With Tk initially set to French, the Studio opens in English. Tests invoke the Sequencer menu, open F6/F7, read the on-screen editor and timing labels, and open the file chooser. The chooser returns the selected filename unchanged. Confirmation dialogs return Yes, No or Cancel as appropriate and restore the parent window's input grab. |
| Editing and history | PREV/NEXT only moves the cursor. BACK and REDO restore the edit, bank and cursor. Waveform edits from the front panel and MIDI use the same English undo and redo labels. Coverage also includes tap input, MIDI legato, knob gestures, project selection and saving. |
| Artwork and controls | Real mouse events on a Tk canvas exercise 24 keys across eleven skins; tests check coordinates, pressed states, cancelled drags, the LCD, and the placement of Record, Clear and Demo. The suite checks 1280 × 720 and a compact 1024 × 600 layout. Panel, menu and editor screenshots and the BACK/REDO animation come from the running Studio. |
| Compatibility | All seven projects from the previous distribution and all seven shipped here opened without a missing instrument. The old sample descriptor in `my_project6.tb303` decoded with the original base frequency. A project-local sample under the previous name takes precedence over a factory alias. All 12 bundled audio files (instruments, music and demos) are byte-for-byte identical to their predecessors. |
| Playback | Tests check Pitch/Time separation, temporary hidden steps, ties, rests, slides, track markers, D.S. and D.C., BAR RESET, cross-bar transitions and exported WAV lengths. Tests compare continuous and segmented rendering, the stereo callback and offline output. |
| Live pattern changes | The current pattern completes before its replacement starts. Tests exercise triplets, swing, unusual lengths, tempo changes, Fwd&Rev, a queued replacement being changed or cancelled, samples and real-time recording. The MIDI clock and fallback mixer are simulated. In the bundled WAV, the pattern is selected at sample 57,330 and takes over at 88,200 (44.1 kHz). |

Mk III also checks the registration of original transport controls, knobs, sixteen steps and footer on all eleven cases; separate lit and depressed states for all 24 keys; pointer fall-through between keys; custom-source fittings; and keyboard/mouse selection including undo after a skin change. The contact sheet and guide images were captured from real Tk windows.

Selector tests cover mouse and keyboard use, exact idle-field pixels after a pointer selection, cancel and undo, and all three drawers on all eleven factory skins at 1024 × 600. An additional Linux X11 pointer run verified window stacking, press-drag-release selection, and click-away dismissal over the piano.

## Previous audio measurements

The Legacy compatibility comparison for the original five Live Lights demo projects used nine TB-303 synth patterns. At 44.1 kHz on the same machine, the largest difference between the original and Legacy floating-point output was 0.0, for both offline rendering and the real-time engine's calculation. The comparison excluded sampled instruments.

The bundled Legacy vs. Classic comparison is 16-bit stereo PCM at 44.1 kHz, 385,875 frames (8.75 seconds). Both excerpts measured −18.0 LUFS after level matching, with sample peaks of −6.24 dBFS for Legacy and −8.38 dBFS for Classic. Matching affects only this demonstration WAV.

The current tests run the DSP in Python without Numba compilation and do not use a physical audio or MIDI device. They do not measure the analog response of a hardware TB-303, the Akai keyboard or a Windows/WSL audio driver. The audio converter's two candidate-rendering profiles are exercised; the full optimizer was not timed.

