# Keyboard Audio Studio — Windows desktop app

Records your microphone while showing the physical keys you press in a live keyboard display. Press **Play / Record** to start. Press **Stop & Export** to finalize the session.

## First launch

1. Extract this ZIP into a normal writable folder, such as Documents\KeyboardAudioStudio. Do not run it from inside the ZIP.
2. Install **Python 3.12, 64-bit**, from https://www.python.org/downloads/windows/ if Python is not already installed. Include the Python launcher and Tcl/Tk options in the installer. No administrator permission is needed for a per-user install.
3. Double-click **Start_Recorder.cmd**. The first launch installs dependencies and the bundled audio encoder from PyPI, requiring internet. Later launches reuse that installation. Recording and exporting happen locally without internet.
4. Choose your microphone. For a laptop microphone array, look for a device named Microphone Array / Intel Smart Sound / Realtek, depending on your drivers. The default Windows input is initially selected. Duplicate names may represent different Windows audio APIs.
5. Select **44100 Hz** and the desired number of channels. If the device rejects those settings, use **48000 Hz** or **1 channel**.
6. Press **Play / Record**, then type while this window stays focused. Click the keyboard diagram if needed. Keys highlight while held; the text below shows your input sequence. The waveform and RMS indicator show the input level. Use the right-hand scrollbar if your screen scaling hides the bottom controls.
7. Press **Stop & Export**. Wait for the saved-session message. Click **Open session** to see your files.

If Windows blocks microphone access, enable Settings > Privacy & security > Microphone > Microphone access and Let desktop apps access your microphone. The microphone opens only after Play; it closes on Stop. Refresh lists available devices without recording audio.

## Create the executable you can double-click

After successfully launching the app once, double-click **Build_Exe.cmd** on Windows. This creates:

    dist\KeyboardAudioStudio\KeyboardAudioStudio.exe

You can subsequently open that EXE directly. Keep the **entire KeyboardAudioStudio folder inside dist** together, including its _internal subfolder. You may copy that complete folder to another compatible Windows x64 computer; Python is not needed on that destination computer. The build computer needs Python and internet for dependencies. The build uses PyInstaller's folder distribution to include PortAudio, NumPy, Tcl/Tk, and FFmpeg.

**This download contains the application source, launcher, and executable builder, not a prebuilt .exe.** A Windows executable must be built on Windows. The package was prepared in a Linux environment; Windows GUI, hardware microphone capture, and Windows executable packaging have not been verified here.

## Session files

Each recording gets a new timestamped folder under **Documents\KeyboardAudioSessions**, or your selected save location. Existing sessions are not overwritten.

| File | Contents |
| --- | --- |
| session.xlsx | Exactly four columns, defined below. |
| audio.mp4 | Audio-only MP4 container containing AAC audio at 192 kbit/s. No video track. Some video-only players may not support audio-only MP4; Windows Media Player or VLC can be used. |
| audio.wav | PCM16 uncompressed recording, preserving all selected channels. Prefer this file for signal processing and machine learning. |
| key_events.csv | Exact software-timestamped key-down and key-up events, physical key name, printable character, and audio sample index. |
| session.json | Device and session details, channel count, sample rate, definitions, timing notes, and capture/export errors. |

AAC encoding is lossy; the MP4 is a convenience copy. Do not use AAC as the only scientific source. WAV is the primary captured PCM16 recording; conversion from float input to PCM16 quantizes to 16 bits. Amplitude is not normalized, and no denoising is performed by this app. Windows or device drivers may still apply microphone enhancements.

## The four Excel columns

There is **one row per 20 ms audio window**, rather than one row per sample. At 44.1 kHz each full window contains 882 samples; at 48 kHz it contains 960. A final partial window is retained.

| Column | Definition |
| --- | --- |
| Time (s) | Start of the window, relative to the first captured audio sample. |
| Frequency (Hz) | Frequency bin with the largest FFT magnitude in channel 1 after removing the mean and applying a Hann window. DC is excluded. Blank for near-silence (RMS below 0.00001) or a constant signal. This is **dominant signal frequency**, not sampling frequency. |
| Amplitude (RMS, 0-1) | RMS amplitude of channel 1 in digital full-scale units. Not volts, Pascals, or calibrated sound pressure level. |
| Key pressed | New key-down events in that time window, separated by ` | ` if there are multiple. Blank when no new key-down occurs. Held keys are not repeated in every row. |

Nominal FFT bin spacing is **50 Hz** with 20 ms windows. A short keyboard click has a broad spectrum; this single frequency is a summary, not a unique key identifier. Use WAV-derived spectra/MFCCs or spectrograms plus key_events.csv for serious model training. With stereo capture, Excel analyzes **channel 1 only** to avoid cancellation from averaging channels; both channels remain in WAV and MP4.

## Key labels and timing

- This is an explicit **focused-window** recording tool. It captures key events only when this app is focused and recording. Audio continues if you switch away, but keyboard labels pause; a visible message explains the gap. Return to the app before typing experimental data.
- The keyboard diagram uses a standard US layout. Physical key labels are uppercase, with a separate printable character in the event CSV. For example, pressing Shift+A labels the physical A key and records `A` as its character.
- OS auto-repeat is suppressed: a held key produces one key-down and one key-up, rather than fictitious repeated physical presses.
- Some system-reserved shortcuts, the Windows key, media keys, and Fn may be intercepted by Windows or firmware and may not reach the app. Fn normally cannot be labeled through ordinary keyboard events.
- The preview is a record of the input sequence, not a text editor. Backspace is shown as `[Backspace]` rather than erasing the previous training label.
- Key timestamps use the monotonic performance clock. Audio sample zero is mapped to that clock using PortAudio's first ADC timestamp. These are **approximate software-aligned timestamps**, not hardware-calibrated measurements. Keyboard event latency, Windows buffering, and driver processing can cause offsets. For labeling experiments, inspect waveforms and refine onset alignment; an electrical key event does not occur at exactly the same time as the acoustic transient.
- `focus_release` events mark held keys cleared when focus is lost; they are not physical key releases.
- Only events within the recorded WAV duration are exported. Initial events before audio begins are omitted.
- The app warns and stops on detected overflow or writer failure. Review session.json before using an affected recording as training data. A one-hour limit keeps sessions manageable and well below classic WAV/Excel size limits.

## Your Dell microphone array

The application detects whatever input channels Windows exposes, offering up to two. Two physical microphones do **not** guarantee two independent raw microphone channels: Windows may expose a beamformed mono signal, processed stereo, or duplicate channels. The app cannot bypass that driver behavior or establish raw independence from the model name. If you need array processing such as time-difference-of-arrival estimation, verify channel independence experimentally or use an interface exposing independent microphone channels.

## Validation included

Run `python test_exports.py` with the dependencies installed. The tests use synthetic signals and a mocked audio interface, without opening a microphone. They check 44.1/48 kHz tone frequency and RMS, silence/DC handling, stereo preservation, waveform writing, window-boundary key labels, exact four-column XLSX output, formula-safe Excel strings, and AAC MP4 encoding/decoding. These tests passed in the preparation environment using its FFmpeg. They do not validate your microphone hardware, Windows GUI behavior, or the Windows EXE build.

## Troubleshooting

- **No input / no waveform:** check Windows input selection, permissions, and microphone mute. Close applications holding the input in exclusive mode, then Refresh.
- **Format error:** try 48000 Hz, one channel, or another API entry for the same microphone.
- **MP4 export failure:** the WAV and key-event CSV remain. Read the warning and session.json. The build must include imageio_ffmpeg's bundled binary.
- **Startup failure:** run Start_Recorder.cmd from the extracted folder and keep the terminal error visible. Python 3.12 x64 is the recommended setup.
- **Poor acoustic classification:** record a quiet-room baseline, keep position consistent, and test on a separate session. If possible, turn off Windows microphone noise suppression and automatic gain control in the device's input settings.

Dependencies: NumPy, python-sounddevice/PortAudio, XlsxWriter, and imageio-ffmpeg/FFmpeg. Their respective licenses apply. The build process bundles the dependencies supplied by those packages.
