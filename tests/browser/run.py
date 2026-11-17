"""Real browser regression tests, executed exclusively on isolated GitHub CI runners."""
import os,re
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
if os.environ.get('CI')!='true':raise SystemExit('Run this suite on CI, not against a user workstation.')
base='http://127.0.0.1:8000'
password=os.environ['DMS_DEMO_PASSWORD']
artifacts=Path('test-results');artifacts.mkdir(exist_ok=True)

def login(page,username):
 page.goto(base+'/login/')
 page.locator('input[name=username]').fill(username)
 page.locator('input[name=password]').fill(password)
 page.get_by_role('button',name='Anmelden',exact=True).click()
 expect(page.locator('.account-name')).to_be_visible()

def upload(page,number,qmb=False):
 page.goto(base+'/new/')
 expect(page.locator('label[for=id_document_type] .required-marker')).to_have_count(1)
 page.locator('[name=document_type]').select_option(label='Arbeitsanweisungen')
 page.locator('[name=number]').fill(number)
 page.locator('[name=title]').fill(number+' Dokument')
 page.locator('[name=department]').select_option(label='Informationstechnik')
 page.locator('[name=file]').set_input_files({'name':'ci.txt','mimeType':'text/plain','buffer':b'Synthetic browser fixture'})
 page.get_by_role('button',name='Hochladen und direkt freigeben' if qmb else 'Zur QMB-Freigabe senden',exact=True).click()
 expect(page).to_have_url(re.compile(r'/versions/\d+/$'))
 return page.url

with sync_playwright() as p:
 browser=p.chromium.launch()
 for device,options in [('desktop',{'viewport':{'width':1440,'height':1000}}),('tablet',{'viewport':{'width':820,'height':1180},'is_mobile':True,'has_touch':True})]:
  contexts=[]
  try:
   pages={}
   for username in ('autor','pruefer','leser'):
    context=browser.new_context(**options);context.tracing.start(screenshots=True,snapshots=True,sources=True);contexts.append(context)
    page=context.new_page();login(page,username);pages[username]=page
   author,qmb,reader=(pages[name] for name in ('autor','pruefer','leser'))
   number='CI-AUTHOR-'+device
   detail=upload(author,number)
   qmb.goto(base+'/tasks/');expect(qmb.locator('main')).to_contain_text(number)
   qmb.goto(detail);qmb.locator('[name=comment]').fill('Bitte ergänzen')
   qmb.locator('button[value=reject]').click()
   author.goto(detail);expect(author.locator('main')).to_contain_text('Bitte ergänzen')
   author.locator('button[value=submit]').click()
   qmb.goto(detail);qmb.locator('button[value=approve]').click()
   expect(qmb.locator('button[value=approve]')).to_have_count(0)
   reader.goto(base+'/documents/');reader.locator('#q').fill(number)
   row=reader.locator('#document-rows tr').filter(has_text=number)
   expect(row).to_have_count(1)
   expect(row.get_by_role('link',name='Dokumentlink')).to_have_attribute('href',re.compile('/d/arbeitsanweisungen/'))
   row.get_by_role('link',name='Dokumentlink').click()
   expect(reader).to_have_url(re.compile(r'/versions/\d+/files/\d+/viewer/'))
   own=upload(qmb,'CI-QMB-'+device,True)
   expect(qmb.locator('.badge').filter(has_text='Freigegeben').first).to_be_visible()
   expect(qmb.locator('main')).to_contain_text('QMB_DIRECT_RELEASE')
   reader.goto(base+'/documents/');reader.locator('#q').fill('CI-LAZY')
   expect(reader.locator('#document-rows tr')).to_have_count(30)
   reader.locator('.table-wrap').evaluate('(node)=>node.scrollTop=node.scrollHeight')
   expect(reader.locator('#document-rows tr')).to_have_count(32)
   reader.get_by_role('link',name=re.compile('^Dokumentnummer')).click()
   expect(reader.locator('th[aria-sort=ascending]')).to_have_count(1)
   reader.get_by_role('link',name=re.compile('^Dokumentnummer')).click()
   expect(reader.locator('#document-rows tr').first).to_contain_text('CI-LAZY-031')
   if device=='tablet':
    qmb.goto(base+'/new/')
    assert qmb.evaluate('document.documentElement.scrollWidth<=window.innerWidth+1'),'Page overflows tablet viewport'
   qmb.screenshot(path=str(artifacts/(device+'-upload.png')),full_page=True)
   print(device+': login, author review/rejection/approval, QMB direct release, stable links, live search, lazy loading and sorting passed.')
  except Exception:
   for index,context in enumerate(contexts):
    for page in context.pages:page.screenshot(path=str(artifacts/f'{device}-{index}-failure.png'),full_page=True)
    context.tracing.stop(path=str(artifacts/f'{device}-{index}-trace.zip'))
   raise
  finally:
   for context in contexts:context.close()
 browser.close()
