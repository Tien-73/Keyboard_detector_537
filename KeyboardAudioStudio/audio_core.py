"""Audio analysis and session export; does not access a microphone or keyboard."""
from pathlib import Path
import csv
import json
import subprocess
import wave
import numpy as np
import xlsxwriter

WINDOW_MS = 20


def frame_features(samples, sample_rate):
    """RMS (digital full scale) and Hann-window FFT peak, excluding DC.

    Channel 1 is the analysis channel. All recorded channels remain in audio files.
    Frequency is a bin center, not an instantaneous frequency or sampling rate.
    """
    x = np.asarray(samples, dtype=np.float64)
    if x.ndim == 2:
        x = x[:, 0]
    if not len(x):
        return None, 0.0
    rms = float(np.sqrt(np.mean(x * x)))
    if len(x) < 4 or rms < 1e-5:
        return None, rms
    spectrum = np.abs(np.fft.rfft((x - x.mean()) * np.hanning(len(x))))
    spectrum[0] = 0
    if spectrum.max() < 1e-10:
        return None, rms
    peak = int(np.argmax(spectrum))
    return peak * sample_rate / len(x), rms


def export_session(folder, events, capture, ffmpeg_exe=None):
    folder = Path(folder)
    wav_path = folder / 'audio.wav'
    metadata = dict(capture)
    errors = []
    with wave.open(str(wav_path), 'rb') as source:
        sr = source.getframerate()
        channels = source.getnchannels()
        n = source.getnframes()
    duration = n / sr
    # Only events within the actual captured audio are exported.
    events = sorted((e for e in events if 0 <= e['time'] < duration), key=lambda e: e['time'])
    metadata.update(duration_seconds=duration, sample_rate_hz=sr, channels=channels,
                    pcm_bits=16, analysis_channel=1, analysis_window_ms=WINDOW_MS,
                    frequency_definition='Largest non-DC Hann-window FFT magnitude; bin center in Hz',
                    amplitude_definition='RMS digital amplitude relative to full scale (0 to 1)',
                    keyboard_scope='Only this application while recording and focused',
                    synchronization='PortAudio ADC timestamps mapped to perf_counter at first callback; approximate, not hardware-calibrated',
                    key_events=len(events))
    # Preserve exact timestamps before potentially expensive export work.
    with (folder / 'key_events.csv').open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['time_seconds', 'event', 'key', 'character', 'audio_sample_index'])
        for e in events:
            writer.writerow([f"{e['time']:.9f}", e['event'], e['key'], e.get('character', ''),
                             int(e['time'] * sr)])
    metadata_path = folder / 'session.json'
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    if not n:
        return ['No audio frames received. Check microphone permissions and input device.']
    try:
        with xlsxwriter.Workbook(str(folder / 'session.xlsx'),
                                 {'constant_memory': True, 'strings_to_formulas': False,
                                  'strings_to_urls': False}) as book:
            sheet = book.add_worksheet('Recording')
            heading = book.add_format({'bold': True, 'bg_color': '#18314C', 'font_color': '#FFFFFF'})
            number = book.add_format({'num_format': '0.000000'})
            sheet.write_row(0, 0, ['Time (s)', 'Frequency (Hz)', 'Amplitude (RMS, 0-1)', 'Key pressed'], heading)
            sheet.freeze_panes(1, 0)
            sheet.set_column(0, 0, 14, number)
            sheet.set_column(1, 1, 19, number)
            sheet.set_column(2, 2, 25, number)
            sheet.set_column(3, 3, 40)
            sheet.write_comment('A1', 'Start of each 20 ms audio window, relative to first audio sample.')
            sheet.write_comment('B1', 'Dominant non-DC frequency in channel 1, using a Hann-window FFT. Not sampling rate. Blank for silence. Nominal bin spacing: 50 Hz.')
            sheet.write_comment('C1', 'Root-mean-square sample amplitude in channel 1. Digital full scale, not volts or sound pressure.')
            sheet.write_comment('D1', 'Key-down events occurring in this window. Multiple events separated by |. Empty means no new key-down. Exact down/up events are in key_events.csv.')
            downs = [e for e in events if e['event'] == 'down']
            event_index = 0
            chunk = round(sr * WINDOW_MS / 1000)
            position = 0
            row = 1
            with wave.open(str(wav_path), 'rb') as source:
                while True:
                    raw = source.readframes(chunk)
                    if not raw:
                        break
                    samples = np.frombuffer(raw, dtype='<i2').reshape(-1, channels).astype(np.float64) / 32768
                    count = len(samples)
                    start, end = position / sr, (position + count) / sr
                    freq, rms = frame_features(samples, sr)
                    pressed = []
                    while event_index < len(downs) and downs[event_index]['time'] < end:
                        event = downs[event_index]
                        if event['time'] >= start:
                            pressed.append(event['key'])
                        event_index += 1
                    sheet.write_number(row, 0, start)
                    if freq is not None:
                        sheet.write_number(row, 1, freq)
                    sheet.write_number(row, 2, rms)
                    sheet.write_string(row, 3, ' | '.join(pressed))
                    row += 1
                    position += count
            sheet.autofilter(0, 0, max(1, row - 1), 3)
    except Exception as exc:
        errors.append(f'Excel export failed: {exc}')
    try:
        if ffmpeg_exe is None:
            import imageio_ffmpeg
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        target = folder / 'audio.mp4'
        result = subprocess.run([str(ffmpeg_exe), '-hide_banner', '-loglevel', 'error', '-y',
                                 '-i', str(wav_path), '-vn', '-c:a', 'aac', '-b:a', '192k',
                                 '-movflags', '+faststart', str(target)],
                                capture_output=True, text=True, timeout=600,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            target.unlink(missing_ok=True)
            raise RuntimeError(result.stderr[-1500:])
    except Exception as exc:
        errors.append(f'MP4 export failed (WAV retained): {exc}')
    metadata['export_errors'] = errors
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    return errors
