"""Resource-bounded subprocess for private, derived PDF reading copies."""
import io
import json
import sys
from pathlib import Path
from xml.sax.saxutils import escape


def main():
    import resource
    resource.setrlimit(resource.RLIMIT_CPU,(25,25))
    resource.setrlimit(resource.RLIMIT_FSIZE,(60*1024*1024,60*1024*1024))
    if sys.platform!='darwin':
        resource.setrlimit(resource.RLIMIT_AS,(768*1024*1024,768*1024*1024))
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing
    from reportlab.graphics import renderPDF
    from pypdf import PdfReader,PdfWriter
    source,output,metadata = map(Path,sys.argv[1:])
    meta = json.loads(metadata.read_text())
    font = 'Helvetica'
    for fontpath in ['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf','/System/Library/Fonts/Supplemental/Arial.ttf']:
        if Path(fontpath).exists():
            pdfmetrics.registerFont(TTFont('ReadingFont',fontpath))
            font = 'ReadingFont'
            break
    raw = source.read_bytes()
    if meta['suffix']=='.txt':
        if len(raw)>1024*1024:
            raise ValueError('Text preview size limit')
        stream = io.BytesIO()
        style = getSampleStyleSheet()['BodyText']
        style.fontName = font
        story = []
        for line in raw.decode('utf-8',errors='replace').splitlines():
            # Long tokens are wrapped; input markup is never interpreted.
            story.append(Paragraph(escape(line) or ' ',style))
            story.append(Spacer(1,3))
        SimpleDocTemplate(stream,pagesize=A4,topMargin=65,bottomMargin=80).build(story or [Paragraph(' ',style)])
        raw = stream.getvalue()
    elif meta['suffix']!='.pdf':
        raise ValueError('No PDF reading copy for this format')
    reader = PdfReader(io.BytesIO(raw))
    if reader.is_encrypted or len(reader.pages)>300:
        raise ValueError('Encrypted PDF or page limit')
    writer = PdfWriter()
    for index,page in enumerate(reader.pages,1):
        page.transfer_rotation_to_content()
        for key in ['/Annots','/AA']:
            if key in page:
                del page[key]
        width,height = float(page.mediabox.width),float(page.mediabox.height)
        if not 150<=width<=3000 or not 150<=height<=3000:
            raise ValueError('Unsupported page dimensions')
        # Reserve a fresh margin; do not cover source content with control information.
        new = writer.add_blank_page(width=width,height=height+100)
        from pypdf import Transformation
        new.merge_transformed_page(page,Transformation().translate(tx=0,ty=70))
        stamp = io.BytesIO()
        c = canvas.Canvas(stamp,pagesize=(width,height+100))
        c.setFont(font,8)
        c.drawString(12,height+83,(meta['number']+' | '+meta['version']+' | '+meta['status'])[:130])
        c.drawString(12,49,('Freigabe: '+meta['approved_on']+' | Seite '+str(index)+' / '+str(len(reader.pages)))[:130])
        c.drawString(12,35,'Abgeleitete Lesefassung. Aktualität vor Verwendung im DMS prüfen.')
        c.setFont(font,6)
        c.drawString(12,22,meta['url'][:180])
        qr = QrCodeWidget(meta['url'])
        drawing = Drawing(50,50,transform=[50/qr.barWidth,0,0,50/qr.barHeight,0,0])
        drawing.add(qr)
        renderPDF.draw(drawing,c,width-62,8)
        c.linkURL(meta['url'],(8,5,width-5,65),relative=0,thickness=0)
        c.save()
        new.merge_page(PdfReader(io.BytesIO(stamp.getvalue())).pages[0])
    writer.add_metadata({'/Title':meta['number']+' '+meta['title'],'/Subject':'Abgeleitete DMS-Lesefassung'})
    with output.open('wb') as stream:
        writer.write(stream)

if __name__=='__main__':
    main()
