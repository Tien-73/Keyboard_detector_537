"""Keyboard Audio Studio: local, focused-window recording for labeled experiments."""
import json
import os
from pathlib import Path
import queue
import threading
import time
import traceback
import wave
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import numpy as np
import sounddevice as sd
from audio_core import export_session

BG = '#0b1220'
PANEL = '#142035'
TEXT = '#edf3ff'
MUTED = '#9eafc9'
ACCENT = '#58e0bd'

ROWS = [
 [('Esc',1),('F1',1),('F2',1),('F3',1),('F4',1),('F5',1),('F6',1),('F7',1),('F8',1),('F9',1),('F10',1),('F11',1),('F12',1),('Delete',1.4)],
 [('`',1),('1',1),('2',1),('3',1),('4',1),('5',1),('6',1),('7',1),('8',1),('9',1),('0',1),('-',1),('=',1),('Backspace',2)],
 [('Tab',1.5),('Q',1),('W',1),('E',1),('R',1),('T',1),('Y',1),('U',1),('I',1),('O',1),('P',1),('[',1),(']',1),('\\',1.5)],
 [('Caps Lock',1.8),('A',1),('S',1),('D',1),('F',1),('G',1),('H',1),('J',1),('K',1),('L',1),(';',1),("'",1),('Enter',2.2)],
 [('Shift L',2.3),('Z',1),('X',1),('C',1),('V',1),('B',1),('N',1),('M',1),(',',1),('.',1),('/',1),('Shift R',2.7)],
 [('Ctrl L',1.5),('Win L',1),('Alt L',1.5),('Space',6),('Alt R',1.5),('Ctrl R',1.5),('Left',1),('Down',1),('Up',1),('Right',1)]
]
ALIASES = {'Escape':'Esc','space':'Space','Return':'Enter','BackSpace':'Backspace',
           'Caps_Lock':'Caps Lock','Shift_L':'Shift L','Shift_R':'Shift R',
           'Control_L':'Ctrl L','Control_R':'Ctrl R','Alt_L':'Alt L','Alt_R':'Alt R',
           'Super_L':'Win L','Win_L':'Win L','Meta_L':'Win L','ISO_Left_Tab':'Tab',
           'grave':'`','asciitilde':'`','minus':'-','underscore':'-','equal':'=',
           'plus':'=','bracketleft':'[','braceleft':'[','bracketright':']','braceright':']',
           'backslash':'\\','bar':'\\','semicolon':';','colon':';','apostrophe':"'",'quotedbl':"'",
           'comma':',','less':',','period':'.','greater':'.','slash':'/','question':'/'}
SHIFT_DIGITS = dict(zip(')!@#$%^&*(', '0123456789'))


def key_name(event):
    name = event.keysym
    if name in ALIASES:
        return ALIASES[name]
    if name in SHIFT_DIGITS:
        return SHIFT_DIGITS[name]
    if len(name) == 1 and name.isalpha():
        return name.upper()
    # Windows virtual key codes preserve physical number/punctuation keys with Shift.
    if os.name == 'nt':
        if 48 <= event.keycode <= 57 or 65 <= event.keycode <= 90:
            return chr(event.keycode)
        oem = {186:';',187:'=',188:',',189:'-',190:'.',191:'/',192:'`',219:'[',220:'\\',221:']',222:"'"}
        if event.keycode in oem:
            return oem[event.keycode]
    return name


class Recorder:
    def __init__(self, folder, device, rate, channels):
        self.folder, self.rate, self.channels = Path(folder), rate, channels
        self.device = device
        self.blocks = queue.Queue(maxsize=256)
        self.latest = np.zeros(1024)
        self.warnings = []
        self.error = None
        self.origin = None
        self.frames = 0
        self.stream = None
        self.writer = None
        self.stopping = False

    def start(self):
        self.wav = wave.open(str(self.folder / 'audio.wav'), 'wb')
        self.wav.setnchannels(self.channels)
        self.wav.setsampwidth(2)
        self.wav.setframerate(self.rate)
        self.writer = threading.Thread(target=self._write, daemon=True)
        self.writer.start()
        try:
            self.stream = sd.InputStream(device=self.device, samplerate=self.rate,
                                         channels=self.channels, dtype='float32',
                                         blocksize=1024, callback=self._callback)
            self.stream.start()
        except Exception:
            self.stop()
            raise

    def _callback(self, data, count, timing, status):
        now = time.perf_counter()
        if self.origin is None:
            # Both PortAudio times use the same clock. Offset ADC start into perf_counter.
            self.origin = now - (timing.currentTime - timing.inputBufferAdcTime)
        if status:
            warning = str(status)
            if warning not in self.warnings:
                self.warnings.append(warning)
            if status.input_overflow:
                self.error = 'Audio input overflow: recording stopped; timing may be discontinuous.'
        if self.stopping:
            return
        try:
            self.blocks.put_nowait(data.copy())
        except queue.Full:
            self.error = 'Disk writer could not keep up: recording stopped; some audio was lost.'
        self.latest = data[:, 0].copy()
        self.frames += count
        if self.frames / self.rate >= 3600:
            self.error = 'One-hour recording limit reached. Start a new session to continue.'

    def _write(self):
        try:
            while True:
                data = self.blocks.get()
                if data is None:
                    break
                pcm = np.clip(np.rint(data * 32768), -32768, 32767).astype('<i2')
                self.wav.writeframesraw(pcm.tobytes())
        except Exception as exc:
            self.error = f'Audio write failed: {exc}'
        finally:
            self.wav.close()

    def stop(self):
        self.stopping = True
        if self.stream:
            try:
                self.stream.stop()
            except Exception as exc:
                self.error = self.error or f'Audio stream stop failed: {exc}'
            finally:
                try:
                    self.stream.close()
                except Exception as exc:
                    self.error = self.error or f'Audio stream close failed: {exc}'
        if self.writer:
            while self.writer.is_alive():
                try:
                    self.blocks.put(None, timeout=0.1)
                    break
                except queue.Full:
                    pass
            self.writer.join()


class App:
    def __init__(self, root):
        self.root = root
        root.title('Keyboard Audio Studio')
        root.geometry('1120x860')
        root.minsize(940, 650)
        root.configure(bg=BG)
        self.recorder = None
        self.recording = False
        self.saving = False
        self.events = []
        self.held = set()
        self.rects = {}
        self.last_folder = None
        self.ui_queue = queue.Queue()
        self.directory = Path.home() / 'Documents' / 'KeyboardAudioSessions'
        self._theme()
        # Scroll vertically on laptops using large Windows display scaling.
        shell = tk.Frame(root, bg=BG)
        shell.pack(fill='both', expand=True)
        self.page = tk.Canvas(shell, bg=BG, highlightthickness=0)
        scroll = ttk.Scrollbar(shell, orient='vertical', command=self.page.yview)
        scroll.pack(side='right', fill='y')
        self.page.pack(side='left', fill='both', expand=True)
        self.page.configure(yscrollcommand=scroll.set)
        self.body = tk.Frame(self.page, bg=BG)
        page_window = self.page.create_window((0, 0), window=self.body, anchor='nw')
        self.body.bind('<Configure>', lambda e: self.page.configure(scrollregion=self.page.bbox('all')))
        self.page.bind('<Configure>', lambda e: self.page.itemconfigure(page_window, width=e.width))
        root.bind('<MouseWheel>', lambda e: self.page.yview_scroll(int(-e.delta/120), 'units'))
        self._build()
        self.refresh_devices()
        root.bind('<KeyPress>', self.key_down)
        root.bind('<KeyRelease>', self.key_up)
        root.bind('<FocusOut>', self.focus_lost)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(40, self.tick)

    def _theme(self):
        s = ttk.Style()
        s.theme_use('clam')
        s.configure('TCombobox', padding=7, fieldbackground='#ffffff', foreground='#152237')
        s.configure('TButton', padding=(15, 9), font=('Segoe UI', 10))
        s.configure('Play.TButton', background=ACCENT, foreground=BG, font=('Segoe UI', 11, 'bold'))
        s.map('Play.TButton', background=[('active', '#9df3d8')])

    def label(self, parent, text, size=10, color=TEXT, **kw):
        return tk.Label(parent, text=text, font=('Segoe UI', size), fg=color, bg=parent['bg'], **kw)

    def _build(self):
        header = tk.Frame(self.body, bg=BG)
        header.pack(fill='x', padx=30, pady=(22, 15))
        self.label(header, 'KEYBOARD / AUDIO', 10, ACCENT).pack(anchor='w')
        self.label(header, 'Capture the sound. Label every key.', 25).pack(anchor='w', pady=(5, 3))
        self.label(header, 'Local recording workspace  •  20 ms analysis windows  •  Physical key labels', 10, MUTED).pack(anchor='w')
        settings = tk.Frame(self.body, bg=PANEL, padx=16, pady=12)
        settings.pack(fill='x', padx=30)
        self.label(settings, 'MICROPHONE', 9, MUTED).grid(row=0,column=0,sticky='w')
        self.label(settings, 'SAMPLE RATE', 9, MUTED).grid(row=0,column=1,sticky='w',padx=12)
        self.label(settings, 'CHANNELS', 9, MUTED).grid(row=0,column=2,sticky='w')
        self.device_box = ttk.Combobox(settings, state='readonly', width=62)
        self.device_box.grid(row=1,column=0,sticky='ew',pady=(6,0))
        self.device_box.bind('<<ComboboxSelected>>', self.device_changed)
        self.rate_box = ttk.Combobox(settings, state='readonly', values=['44100','48000'], width=10)
        self.rate_box.set('44100')
        self.rate_box.grid(row=1,column=1,padx=12,pady=(6,0))
        self.channels_box = ttk.Combobox(settings, state='readonly', values=['1','2'], width=8)
        self.channels_box.set('1')
        self.channels_box.grid(row=1,column=2,pady=(6,0))
        self.refresh_button = ttk.Button(settings, text='Refresh', command=self.refresh_devices)
        self.refresh_button.grid(row=1,column=3,padx=(12,0),pady=(6,0))
        settings.columnconfigure(0, weight=1)
        controls = tk.Frame(self.body,bg=BG)
        controls.pack(fill='x',padx=30,pady=16)
        self.play_button = ttk.Button(controls,text='▶  Play / Record',style='Play.TButton', command=self.start)
        self.play_button.pack(side='left')
        self.stop_button = ttk.Button(controls,text='■  Stop & Export', command=self.stop,state='disabled')
        self.stop_button.pack(side='left',padx=10)
        self.clock = self.label(controls,'00:00.0',20)
        self.clock.pack(side='right')
        self.status = self.label(controls,'READY',10,ACCENT)
        self.status.pack(side='right',padx=20)
        self.scope = tk.Canvas(self.body,height=105,bg=PANEL,highlightthickness=0)
        self.scope.pack(fill='x',padx=30)
        self.scope.create_text(16,15,text='LIVE INPUT · CHANNEL 1',fill=MUTED,anchor='w',font=('Segoe UI',9))
        self.focus_hint = self.label(self.body,'Press Play, then type here. Key capture works only while this window is focused.',10,MUTED)
        self.focus_hint.pack(anchor='w',padx=30,pady=(14,8))
        self.keyboard = tk.Canvas(self.body,height=285,bg=BG,highlightthickness=0,takefocus=True)
        self.keyboard.pack(fill='x',padx=26)
        self.keyboard.bind('<Configure>',lambda e:self.draw_keyboard())
        self.keyboard.bind('<Button-1>',lambda e:self.keyboard.focus_set())
        self.preview = tk.Text(self.body,height=3,bg=PANEL,fg=TEXT,insertbackground=ACCENT,
                               relief='flat',font=('Consolas',13),padx=12,pady=10,state='disabled',takefocus=False)
        self.preview.pack(fill='x',padx=30,pady=(8,10))
        bottom = tk.Frame(self.body,bg=BG)
        bottom.pack(fill='x',padx=30)
        self.folder_label = self.label(bottom,str(self.directory),9,MUTED,anchor='w')
        self.folder_label.pack(side='left',fill='x',expand=True)
        self.folder_button = ttk.Button(bottom,text='Save location…',command=self.choose_folder)
        self.folder_button.pack(side='right')
        self.open_button = ttk.Button(bottom,text='Open session',command=self.open_folder,state='disabled')
        self.open_button.pack(side='right',padx=8)
        self.label(self.body,'Exports: session.xlsx  /  audio.mp4 (AAC)  /  audio.wav (PCM)  /  key_events.csv  /  session.json',9,MUTED).pack(anchor='w',padx=30,pady=(10,4))
        self.label(self.body,'Excel: window start time · dominant frequency · RMS amplitude · new key presses. WAV + event CSV are the training data.',9,MUTED).pack(anchor='w',padx=30)

    def draw_keyboard(self):
        self.keyboard.delete('all')
        self.rects = {}
        width = max(900,self.keyboard.winfo_width()) - 8
        for row, keys in enumerate(ROWS):
            x = 4
            total = sum(size for _,size in keys)
            row_unit = (width - (len(keys)-1)*5)/total
            for name,size in keys:
                w = row_unit*size
                rect = self.keyboard.create_rectangle(x,row*46+3,x+w,row*46+43,
                                fill=ACCENT if name in self.held else PANEL,outline='#263952',width=1)
                self.keyboard.create_text(x+w/2,row*46+23,text=name,
                                fill=BG if name in self.held else TEXT,font=('Segoe UI',9))
                self.rects[name] = rect
                x += w+5

    def refresh_devices(self):
        try:
            devices = sd.query_devices()
            apis = sd.query_hostapis()
            self.inputs = [(i,d) for i,d in enumerate(devices) if d['max_input_channels']>0]
            self.device_box['values'] = [f"{i}: {d['name']} [{apis[d['hostapi']]['name']}]" for i,d in self.inputs]
            if not self.inputs:
                raise RuntimeError('No microphone found. Enable a microphone in Windows Settings > System > Sound > Input.')
            default = sd.default.device[0]
            selected = next((j for j,(i,d) in enumerate(self.inputs) if i == default),0)
            self.device_box.current(selected)
            self.device_changed()
        except Exception as exc:
            self.status.configure(text='NO INPUT',fg='#ffbd83')
            messagebox.showerror('Microphone',str(exc))

    def device_changed(self, _=None):
        selected = self.device_box.current()
        if selected < 0:
            return
        _, info = self.inputs[selected]
        maximum = min(2,int(info['max_input_channels']))
        self.channels_box['values'] = [str(i) for i in range(1,maximum+1)]
        self.channels_box.set(str(maximum))

    def choose_folder(self):
        chosen = filedialog.askdirectory(initialdir=str(self.directory.parent))
        if chosen:
            self.directory = Path(chosen)
            self.folder_label.configure(text=chosen)

    def settings_enabled(self, enabled):
        for box in (self.device_box,self.rate_box,self.channels_box):
            box.configure(state='readonly' if enabled else 'disabled')
        for button in (self.refresh_button,self.folder_button,self.play_button):
            button.configure(state='normal' if enabled else 'disabled')

    def start(self):
        if self.recording or self.saving:
            return
        selected = self.device_box.current()
        if selected < 0:
            messagebox.showerror('Microphone','Select a microphone first.')
            return
        device, info = self.inputs[selected]
        rate, channels = int(self.rate_box.get()), int(self.channels_box.get())
        try:
            sd.check_input_settings(device=device,channels=channels,samplerate=rate,dtype='float32')
        except Exception as exc:
            messagebox.showerror('Unsupported input format',f'{exc}\n\nTry 48000 Hz or 1 channel. Windows may expose an array as a processed mono input.')
            return
        try:
            folder = self.directory / datetime.now().strftime('%Y-%m-%d_%H-%M-%S_%f')
            folder.mkdir(parents=True,exist_ok=False)
            self.events = []
            self.held.clear()
            self.recorder = Recorder(folder,device,rate,channels)
            self.capture = {'started_local':datetime.now().astimezone().isoformat(),
                            'device':dict(info),'device_index':device,'requested_sample_rate':rate}
            self.recorder.start()
        except Exception as exc:
            messagebox.showerror('Cannot record',f'{exc}\n\nCheck Windows Settings > Privacy & security > Microphone > Let desktop apps access your microphone.')
            return
        self.recording = True
        self.focus_hint.configure(text='Recording keys in this window. Keep this window focused while typing.', fg=MUTED)
        self.settings_enabled(False)
        self.stop_button.configure(state='normal')
        self.status.configure(text='● RECORDING',fg=ACCENT)
        self.preview.configure(state='normal')
        self.preview.delete('1.0','end')
        self.preview.configure(state='disabled')
        self.keyboard.focus_set()
        self.draw_keyboard()

    def key_down(self,event):
        if not self.recording:
            return
        self.focus_hint.configure(text='Recording keys in this window. Keep this window focused while typing.', fg=MUTED)
        name = key_name(event)
        if name in self.held:
            return 'break'  # suppress OS repeat; labels correspond to physical key-downs
        self.held.add(name)
        self.events.append({'perf':time.perf_counter(),'event':'down','key':name,'character':event.char if event.char and event.char.isprintable() else ''})
        self.preview.configure(state='normal')
        token = event.char if event.char and event.char.isprintable() else f'[{name}]'
        self.preview.insert('end',token)
        self.preview.see('end')
        self.preview.configure(state='disabled')
        self.draw_keyboard()
        return 'break'

    def key_up(self,event):
        if not self.recording:
            return
        name = key_name(event)
        # Tk keysym can change if Shift was released first; use held-key fallback.
        if name in self.held:
            self.held.remove(name)
            self.events.append({'perf':time.perf_counter(),'event':'up','key':name,'character':''})
        self.draw_keyboard()
        return 'break'

    def focus_lost(self,event):
        if self.recording:
            self.root.after(30,self.check_focus)

    def check_focus(self):
        if not self.recording:
            return
        if self.root.focus_displayof() is None:
            now = time.perf_counter()
            for name in self.held:
                self.events.append({'perf':now,'event':'focus_release','key':name,'character':''})
            self.held.clear()
            self.draw_keyboard()
            self.focus_hint.configure(text='Window unfocused: audio continues; keyboard labels pause. Click the keyboard to resume.',fg='#ffbd83')
        else:
            self.focus_hint.configure(text='Recording keys in this window. Keep this window focused while typing.',fg=MUTED)

    def stop(self):
        if not self.recording:
            return
        self.recording = False
        self.saving = True
        self.stop_button.configure(state='disabled')
        self.status.configure(text='SAVING…',fg='#ffbd83')
        self.held.clear()
        self.draw_keyboard()
        recorder = self.recorder
        events = list(self.events)
        capture = dict(self.capture)
        def finish():
            errors = []
            try:
                recorder.stop()
                capture['capture_warnings'] = recorder.warnings
                capture['capture_error'] = recorder.error
                origin = recorder.origin
                converted = [dict(time=e['perf']-origin,event=e['event'],key=e['key'],character=e['character'])
                             for e in events] if origin is not None else []
                if recorder.error:
                    errors.append(recorder.error)
                errors.extend(export_session(recorder.folder,converted,capture))
            except Exception as exc:
                errors.append(str(exc))
                (recorder.folder / 'export_error.txt').write_text(traceback.format_exc(),encoding='utf-8')
            self.ui_queue.put((recorder.folder,errors))
        threading.Thread(target=finish,daemon=True).start()

    def tick(self):
        if self.recording and self.recorder:
            elapsed = self.recorder.frames / self.recorder.rate
            self.clock.configure(text=f'{int(elapsed//60):02d}:{elapsed%60:04.1f}')
            self.scope.delete('wave')
            data = self.recorder.latest
            w = max(100,self.scope.winfo_width())
            stride = max(1,len(data)//(w//2))
            data = data[::stride]
            points = []
            # Visual gain only. Exported audio/amplitude is never normalized.
            for i,value in enumerate(data):
                points.extend((i*w/max(1,len(data)-1),65-float(value)*120))
            if len(points)>=4:
                self.scope.create_line(points,fill=ACCENT,width=1.3,tags='wave')
            rms = float(np.sqrt(np.mean(self.recorder.latest**2)))
            self.scope.create_text(w-15,15,text=f'RMS {rms:.5f}',fill=MUTED,anchor='e',tags='wave',font=('Consolas',10))
            if self.recorder.error:
                self.stop()
        try:
            folder,errors = self.ui_queue.get_nowait()
            self.saving = False
            self.settings_enabled(True)
            self.last_folder = folder
            self.open_button.configure(state='normal')
            self.status.configure(text='SAVED' if not errors else 'CHECK EXPORT',fg=ACCENT if not errors else '#ffbd83')
            self.focus_hint.configure(text=f'Session saved: {folder.name}. Press Play for a new session.',fg=MUTED)
            if errors:
                messagebox.showwarning('Session needs attention','\n\n'.join(errors)+f'\n\nSession folder: {folder}')
            else:
                messagebox.showinfo('Session saved',f'Excel and audio saved to:\n{folder}\n\nsession.xlsx · audio.mp4 · audio.wav\nkey_events.csv · session.json')
        except queue.Empty:
            pass
        self.root.after(40,self.tick)

    def open_folder(self):
        if self.last_folder:
            if os.name == 'nt':
                os.startfile(str(self.last_folder))
            else:
                import subprocess
                subprocess.Popen(['xdg-open',str(self.last_folder)])

    def close(self):
        if self.saving:
            messagebox.showinfo('Export in progress','Please wait until the session finishes saving.')
        elif self.recording:
            self.stop()
        else:
            self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
