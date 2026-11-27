"""Real raster/OCR integration; synthetic scan, no company documents."""
import io
import json
import os
import subprocess
import shutil
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dms.extract_text import extract


@unittest.skipUnless(shutil.which('tesseract') and shutil.which('pdftoppm'),'OCR tools are not installed')
class OCRIntegrationTests(unittest.TestCase):
    def test_scanned_pdf_becomes_searchable_without_altering_source(self):
        from PIL import Image,ImageDraw,ImageFont
        image=Image.new('RGB',(1600,600),'white')
        font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',60)
        draw=ImageDraw.Draw(image)
        draw.text((80,180),'IMS Arbeitsanweisung Energieverbrauch',fill='black',font=font)
        stream=io.BytesIO();image.save(stream,'PDF',resolution=150)
        content=stream.getvalue()
        result=json.loads(subprocess.run([sys.executable,'-I',str(Path(__file__).resolve().parents[1]/'dms/extract_text.py'),'pdf'],input=content,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=140,check=True,env={'PATH':os.environ['PATH'],'LANG':'C.UTF-8','PYTHONIOENCODING':'utf-8'}).stdout)
        self.assertIn('Energieverbrauch',result['text'])
        self.assertFalse(result['truncated'])
        self.assertEqual(stream.getvalue(),content)
