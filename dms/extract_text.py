"""Bounded text extraction child process. Receives bytes on stdin, no DB secrets."""
import io
import json
import re
import sys
import zipfile

MAX_INPUT = 25*1024*1024
MAX_TEXT = 200000
MAX_XML = 8*1024*1024

class ExtractionError(Exception):
    pass


def local_name(tag):
    return tag.rsplit('}',1)[-1]


def xml_file(archive,name):
    from defusedxml.ElementTree import fromstring
    if archive.getinfo(name).file_size>MAX_XML:
        raise ExtractionError('LIMIT_EXCEEDED')
    data = archive.read(name)
    if len(data)>MAX_XML:
        raise ExtractionError('LIMIT_EXCEEDED')
    return fromstring(data,forbid_dtd=True,forbid_entities=True,forbid_external=True)


def office_text(content,kind):
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        entries = archive.infolist()
        if len(entries)>2000 or sum(e.file_size for e in entries)>32*1024*1024:
            raise ExtractionError('LIMIT_EXCEEDED')
        if kind=='docx':
            names = ['word/document.xml']+[e.filename for e in entries if re.fullmatch(r'word/(?:header|footer)\d+\.xml',e.filename)]
            return ' '.join((element.text or '') for name in names for element in xml_file(archive,name).iter() if local_name(element.tag)=='t')
        if kind=='odt':
            root = xml_file(archive,'content.xml')
            return ' '.join(root.itertext())
        workbook = xml_file(archive,'xl/workbook.xml')
        parts = [element.attrib.get('name','') for element in workbook.iter() if local_name(element.tag)=='sheet']
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            root = xml_file(archive,'xl/sharedStrings.xml')
            strings = [''.join(node.text or '' for node in item.iter() if local_name(node.tag)=='t') for item in root if local_name(item.tag)=='si']
        for name in sorted(e.filename for e in entries if re.fullmatch(r'xl/worksheets/sheet\d+\.xml',e.filename)):
            for cell in xml_file(archive,name).iter():
                if local_name(cell.tag)!='c':
                    continue
                if cell.attrib.get('t')=='inlineStr':
                    parts.append(''.join(n.text or '' for n in cell.iter() if local_name(n.tag)=='t'))
                    continue
                value = next((n.text or '' for n in cell if local_name(n.tag)=='v'),'')
                if cell.attrib.get('t')=='s':
                    index = int(value)
                    if not 0<=index<len(strings):
                        raise ExtractionError('INVALID_FILE')
                    value = strings[index]
                parts.append(value)
        return ' '.join(parts)


def extract(content,kind):
    if len(content)>MAX_INPUT:
        raise ExtractionError('LIMIT_EXCEEDED')
    if kind=='txt':
        text = content.decode('utf-8-sig')
    elif kind in ('docx','odt','xlsx'):
        text = office_text(content,kind)
    elif kind=='pdf':
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content),strict=False)
        if reader.is_encrypted:
            raise ExtractionError('ENCRYPTED_FILE')
        if len(reader.pages)>200:
            raise ExtractionError('LIMIT_EXCEEDED')
        chunks = []
        count = 0
        for page in reader.pages:
            text = page.extract_text() or ''
            chunks.append(text)
            count += len(text)
            if count>MAX_TEXT:
                break
        text = ' '.join(chunks)
    else:
        raise ExtractionError('UNSUPPORTED_FORMAT')
    text = re.sub(r'\s+',' ',re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]',' ',text)).strip()
    return {'text':text[:MAX_TEXT],'truncated':len(text)>MAX_TEXT}


def main():
    import resource
    resource.setrlimit(resource.RLIMIT_CPU,(10,10))
    resource.setrlimit(resource.RLIMIT_FSIZE,(1024*1024,1024*1024))
    if sys.platform.startswith('linux'):
        resource.setrlimit(resource.RLIMIT_AS,(768*1024*1024,768*1024*1024))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    try:
        result = extract(sys.stdin.buffer.read(MAX_INPUT+1),sys.argv[1])
    except ExtractionError as exc:
        result = {'error':str(exc)}
    except (Exception,MemoryError):
        result = {'error':'INVALID_FILE'}
    print(json.dumps(result,ensure_ascii=True))

if __name__=='__main__':
    main()
