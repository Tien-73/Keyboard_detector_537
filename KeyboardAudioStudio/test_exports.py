"""Run: python test_exports.py. Uses synthetic audio; no microphone is accessed."""
import csv
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import wave
import xml.etree.ElementTree as ET
import zipfile
import numpy as np
from audio_core import export_session, frame_features


class ExportsTest(unittest.TestCase):
    def test_features_known_tone_stereo_and_silence(self):
        for sr in (44100, 48000):
            t = np.arange(round(sr*.02))/sr
            x = .5*np.sin(2*np.pi*1000*t)
            freq, rms = frame_features(np.column_stack([x, np.zeros_like(x)]), sr)
            self.assertAlmostEqual(freq,1000,places=5)
            self.assertAlmostEqual(rms,.5/np.sqrt(2),places=5)
            self.assertEqual(frame_features(np.zeros_like(x),sr),(None,0))
            self.assertIsNone(frame_features(np.ones_like(x)*.1,sr)[0])

    def test_full_export_and_event_boundaries(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            sr = 44100
            t = np.arange(sr)/sr
            x = .4*np.sin(2*np.pi*1000*t)
            pcm = np.rint(np.column_stack([x,-x])*32767).astype('<i2')
            with wave.open(str(folder/'audio.wav'),'wb') as f:
                f.setnchannels(2)
                f.setsampwidth(2)
                f.setframerate(sr)
                f.writeframes(pcm.tobytes())
            events = [dict(time=-.001,event='down',key='OUTSIDE'),
                      dict(time=.019,event='down',key='A'),
                      dict(time=.02,event='down',key='B'),
                      dict(time=.021,event='up',key='A'),
                      dict(time=.022,event='down',key='=1+1'),
                      dict(time=1.001,event='down',key='OUTSIDE')]
            ffmpeg = shutil.which('ffmpeg')
            if not ffmpeg:
                self.skipTest('ffmpeg not available')
            self.assertEqual(export_session(folder,events,{'synthetic':True},ffmpeg),[])
            metadata = json.loads((folder/'session.json').read_text())
            self.assertEqual(metadata['duration_seconds'],1)
            self.assertEqual(metadata['channels'],2)
            self.assertEqual(metadata['key_events'],4)
            with (folder/'key_events.csv').open(encoding='utf-8-sig') as f:
                event_rows = list(csv.reader(f))
            self.assertEqual(len(event_rows),5)
            self.assertEqual(event_rows[2][4],'882')
            with zipfile.ZipFile(folder/'session.xlsx') as z:
                xml = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
                ns = {'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                rows = xml.findall('m:sheetData/m:row',ns)
                self.assertEqual(len(rows),51)
                cells = rows[1].findall('m:c',ns)
                self.assertEqual(len(cells),4)
                self.assertEqual(float(cells[1].find('m:v',ns).text),1000)
                self.assertEqual(cells[3].find('m:is/m:t',ns).text,'A')
                self.assertEqual(rows[2].findall('m:c',ns)[3].find('m:is/m:t',ns).text,'B | =1+1')
                self.assertEqual(xml.findall('.//m:f',ns),[])
            result = subprocess.run([ffmpeg,'-v','error','-i',str(folder/'audio.mp4'),'-f','null','-'],capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            probe = shutil.which('ffprobe')
            if probe:
                info=json.loads(subprocess.check_output([probe,'-v','error','-show_streams','-of','json',str(folder/'audio.mp4')]))
                self.assertEqual(info['streams'][0]['codec_name'],'aac')
                self.assertEqual(info['streams'][0]['channels'],2)
                self.assertAlmostEqual(float(info['streams'][0]['duration']),1,places=2)

    def test_recorder_writes_every_channel_and_maps_adc_time(self):
        # Mock the OS interface only, exercise the real callback and disk writer.
        import sys
        import types
        fake = types.ModuleType('sounddevice')
        class Stream:
            def __init__(self, **kwargs): self.kwargs=kwargs
            def start(self):
                import time
                a = np.column_stack([np.full(1024,.25),np.full(1024,-.5)]).astype('float32')
                self.kwargs['callback'](a,1024,types.SimpleNamespace(currentTime=10.02,inputBufferAdcTime=10),False)
            def stop(self): pass
            def close(self): pass
        fake.InputStream=Stream
        old=sys.modules.get('sounddevice')
        sys.modules['sounddevice']=fake
        try:
            import keyboard_audio_studio as gui
            with tempfile.TemporaryDirectory() as d:
                recorder=gui.Recorder(d,0,44100,2)
                recorder.start()
                self.assertIsNotNone(recorder.origin)
                recorder.stop()
                with wave.open(str(Path(d)/'audio.wav'),'rb') as f:
                    self.assertEqual(f.getnframes(),1024)
                    data=np.frombuffer(f.readframes(1024),dtype='<i2').reshape(-1,2)
                    self.assertTrue((data[:,0]==8192).all())
                    self.assertTrue((data[:,1]==-16384).all())
        finally:
            if old: sys.modules['sounddevice']=old
            else: sys.modules.pop('sounddevice',None)


if __name__=='__main__':
    unittest.main(verbosity=2)
