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

def assert_aligned(page,selectors):
 boxes=[page.locator(selector).bounding_box() for selector in selectors]
 assert all(boxes),f'Missing visible controls: {selectors}'
 assert max(b['y'] for b in boxes)-min(b['y'] for b in boxes)<=1,f'Controls are vertically offset: {boxes}'
 assert max(b['height'] for b in boxes)-min(b['height'] for b in boxes)<=1,f'Control heights differ: {boxes}'

def upload(page,number,qmb=False):
 page.goto(base+'/new/')
 expect(page.locator('label[for=id_document_type] .required-marker')).to_have_count(1)
 page.locator('[name=document_type]').select_option(label='Arbeitsanweisungen')
 expect(page.locator('[name=number]')).to_have_value(re.compile(r'AA-\d+'))
 expect(page.locator('[name=number]')).to_have_attribute('required','')
 page.locator('[name=number]').fill(number)
 expect(page.locator('[name=effective_from]')).to_have_attribute('type','date')
 assert_aligned(page,['#id_document_type','#id_number'])
 assert_aligned(page,['#id_department','#id_classification'])
 # A wrapped label must not push just one of the paired controls down.
 label=page.locator('label[for=id_document_type]')
 original=label.inner_html()
 label.evaluate('(node)=>node.firstChild.textContent="Dokumentenart mit einer ausführlichen mehrzeiligen Beschriftung für die Zuordnung im Managementsystem "')
 assert_aligned(page,['#id_document_type','#id_number'])
 label.evaluate('(node,html)=>node.innerHTML=html',original)
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
   qmb.goto(base+'/documents/')
   if device=='desktop':
    assert_aligned(qmb,['#q','#status','#department','#standard'])
   else:
    assert_aligned(qmb,['#q','#status'])
    assert_aligned(qmb,['#department','#standard'])
   qmb.screenshot(path=str(artifacts/(device+'-filters.png')),full_page=True)
   detail=upload(author,number)
   qmb.bring_to_front()
   expect(qmb.locator('[data-task-summary]')).to_have_attribute('data-pending-approvals','1',timeout=20000)
   qmb.goto(base+'/tasks/');expect(qmb.locator('main')).to_contain_text(number)
   qmb.goto(detail)
   expect(qmb.locator('.detail-toolbar')).to_be_visible()
   assert qmb.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),'Detail page overflows viewport'
   qmb.screenshot(path=str(artifacts/(device+'-detail-review.png')),full_page=True)
   qmb.locator('[name=comment]').fill('Bitte ergänzen')
   qmb.locator('button[value=reject]').click()
   author.goto(detail);expect(author.locator('main')).to_contain_text('Bitte ergänzen')
   author.screenshot(path=str(artifacts/(device+'-detail-draft.png')),full_page=True)
   author.get_by_role('link',name='Entwurf und Zuordnungen bearbeiten',exact=True).click()
   expect(author.locator('.edit-sidebar')).to_contain_text('ci.txt')
   assert_aligned(author,['#id_effective_from','#id_classification'])
   author.locator('[name=title]').fill(number+' Dokument aktualisiert')
   assert author.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),'Edit page overflows viewport'
   author.screenshot(path=str(artifacts/(device+'-edit.png')),full_page=True)
   author.get_by_role('button',name='Entwurf speichern',exact=True).click()
   expect(author.locator('[data-document-status=DRAFT]')).to_be_visible()
   author.locator('button[value=submit]').click()
   qmb.goto(detail);qmb.locator('button[value=approve]').click()
   expect(qmb.locator('button[value=approve]')).to_have_count(0)
   qmb.screenshot(path=str(artifacts/(device+'-detail-approved.png')),full_page=True)
   reader.goto(base+'/documents/');reader.locator('#q').fill(number)
   row=reader.locator('#document-rows tr').filter(has_text=number)
   expect(reader.locator('#document-count')).to_have_text('1')
   expect(row).to_have_count(1)
   expect(row.get_by_role('link',name='Dokumentlink')).to_have_attribute('href',re.compile('/d/arbeitsanweisungen/'))
   if device=='desktop':
    assert_aligned(reader,['#q','#department','#standard','.filter-actions button','.filter-actions .button'])
   else:
    assert_aligned(reader,['#q','#department'])
    assert_aligned(reader,['#standard','.filter-actions button','.filter-actions .button'])
   reader.screenshot(path=str(artifacts/(device+'-catalog.png')),full_page=True)
   help_page=reader.context.new_page()
   help_page.goto(base+'/help/')
   expect(help_page.get_by_role('heading',name='Für IT-Admins',exact=True)).to_be_visible()
   assert help_page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),'Help page overflows viewport'
   help_page.screenshot(path=str(artifacts/(device+'-help.png')),full_page=True)
   help_page.close()
   guest_context=browser.new_context(**options);contexts.append(guest_context)
   guest_context.tracing.start(screenshots=True,snapshots=True,sources=True)
   guest=guest_context.new_page();guest.goto(base+'/documents/')
   guest.locator('#q').fill(number)
   expect(guest.locator('#document-count')).to_have_text('1')
   guest_row=guest.locator('#document-rows tr').filter(has_text=number)
   download=guest_context.request.get(base+guest_row.get_by_role('link',name='Herunterladen',exact=True).get_attribute('href'))
   assert download.status==200 and download.body()==b'Synthetic browser fixture'
   guest_row.get_by_role('link',name='Dokumentlink').click()
   expect(guest).to_have_url(re.compile(r'/versions/\d+/files/\d+/viewer/'))
   expect(guest.locator('#pages')).to_have_text(re.compile(r'/\s*1'),timeout=20000)
   permanent_path=row.get_by_role('link',name='Dokumentlink').get_attribute('href')
   row.get_by_role('link',name='Dokumentlink').click()
   expect(reader).to_have_url(re.compile(r'/versions/\d+/files/\d+/viewer/'))
   author.goto(detail)
   author.get_by_role('link',name='Dokumentnummer ändern',exact=True).click()
   changed='CI-RENAMED-'+device
   author.locator('[name=number]').fill(changed)
   author.get_by_role('button',name='Dokumentnummer speichern',exact=True).click()
   guest.goto(base+permanent_path)
   expect(guest.locator('header strong')).to_contain_text(changed)
   own=upload(qmb,'CI-QMB-'+device,True)
   expect(qmb.locator('[data-document-status=APPROVED]')).to_be_visible()
   expect(qmb.locator('main')).to_contain_text('QMB_DIRECT_RELEASE')
   reader.goto(base+'/documents/');reader.locator('#q').fill('CI-LAZY')
   expect(reader.locator('#document-count')).to_have_text('32')
   expect(reader.locator('#document-rows tr').first).to_contain_text('CI-LAZY-000')
   expect(reader.locator('#document-rows tr')).to_have_count(30)
   reader.locator('.table-wrap').evaluate('(node)=>node.scrollTop=node.scrollHeight')
   expect(reader.locator('#document-rows tr')).to_have_count(32)
   reader.locator('#document-rows tr').last.get_by_role('link',name='Dokumentlink').click()
   expect(reader).to_have_url(re.compile(r'/versions/\d+/files/\d+/viewer/'))
   reader.go_back()
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
