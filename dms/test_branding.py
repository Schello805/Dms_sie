import io
from unittest.mock import patch
from PIL import Image
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied,ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError,transaction
from django.test import TestCase,Client,RequestFactory
from . import tests as fixtures,services as s,branding
from .branding_uploads import replace_logo,select_logo,generate_assets
from .version import APP_NAME,APP_VERSION

class BrandingTests(TestCase):
    setUp = fixtures.WorkflowTests.setUp
    enable_runtime_role = fixtures.WorkflowTests.enable_runtime_role

    def admin(self):
        user = get_user_model().objects.create_user('it-brand-admin',password='TestPassword-2026!')
        s.query("INSERT INTO users(auth_user_id,display_name,settings_admin) VALUES (%s,'IT-Admin',true)",[user.pk])
        return user

    def image(self,color='green',size=(100,160),name='logo.png',fmt='PNG'):
        output = io.BytesIO()
        Image.new('RGB',size,color).save(output,format=fmt)
        return SimpleUploadedFile(name,output.getvalue())

    def test_product_name_and_footer_on_all_page_types(self):
        self.client.force_login(self.author)
        for url in ['/','/documents/','/records/','/login/']:
            response = self.client.get(url)
            self.assertContains(response,APP_NAME)
            self.assertContains(response,'Anwendung · Version '+APP_VERSION)
        content = branding.error_response(500).content.decode()
        self.assertIn(APP_NAME,content)
        self.assertIn(APP_VERSION,content)

    def test_only_it_admin_can_replace_or_reset_logo(self):
        for user in (self.reader,self.author,self.reviewer,self.approver):
            with self.assertRaises(PermissionDenied):
                replace_logo(user,self.image(),'Nicht erlaubt')
            with self.assertRaises(PermissionDenied):
                select_logo(user,None,'Nicht erlaubt')
            self.client.force_login(user)
            self.assertEqual(self.client.post('/settings/branding/',{'logo':self.image(),'reason':'Versuch'}).status_code,403)
        self.assertEqual(s.query('SELECT id FROM branding_revisions'),[])

    def test_raster_validation_rejects_active_invalid_oversized_or_animated_uploads(self):
        samples = [SimpleUploadedFile('logo.svg',b'<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>'),
            SimpleUploadedFile('fake.png',b'Not an image'),self.image(size=(32,32)),self.image(size=(4097,64)),
            SimpleUploadedFile('large.png',b'x'*(5*1024*1024+1))]
        animated = io.BytesIO()
        frames = [Image.new('RGB',(100,100),color) for color in ['red','blue']]
        frames[0].save(animated,format='WEBP',save_all=True,append_images=frames[1:],duration=100)
        samples.append(SimpleUploadedFile('animated.webp',animated.getvalue()))
        for sample in samples:
            with self.assertRaises(ValidationError,msg=sample.name):
                generate_assets(sample)
        for fmt in ['PNG','JPEG','WEBP']:
            self.assertTrue(generate_assets(self.image(fmt=fmt))['logo'].startswith(b'\x89PNG'))

    def test_versioned_upload_favicons_and_reset_with_runtime_role(self):
        admin = self.admin()
        self.enable_runtime_role()
        first = replace_logo(admin,self.image(),'Neues Unternehmenslogo')
        self.assertEqual(branding.branding_context()['brand_revision'],f'r{first}')
        responses = []
        for name,size in [('logo.png',(100,160)),('icon-32.png',(32,32)),('icon-180.png',(180,180)),('favicon.ico',(256,256))]:
            response = branding.asset(RequestFactory().get('/assets/branding/'+name,{'v':f'r{first}'}),name)
            body = b''.join(response.streaming_content)
            self.assertEqual(Image.open(io.BytesIO(body)).size,size)
            self.assertIn('immutable',response['Cache-Control'])
            response.file_to_stream.close() if response.file_to_stream else None
        second = replace_logo(admin,self.image('blue'),'Anderes Logo')
        self.assertNotEqual(first,second)
        old = branding.asset(RequestFactory().get('/',{'v':f'r{first}'}),'logo.png')
        self.assertEqual(Image.open(io.BytesIO(b''.join(old.streaming_content))).getpixel((0,0))[:3],(0,128,0))
        select_logo(admin,first,'Erstes Logo wiederherstellen')
        self.assertEqual(branding.branding_context()['brand_revision'],f'r{first}')
        select_logo(admin,None,'Standardlogo wiederherstellen')
        self.assertTrue(branding.branding_context()['brand_revision'].startswith('default-'))
        self.assertEqual(len(s.query('SELECT id FROM branding_revisions')),2)
        with self.assertRaises(DatabaseError),transaction.atomic():
            s.query('DELETE FROM branding_revisions WHERE id=%s',[first])
        self.assertEqual(len(s.query("SELECT id FROM audit_events WHERE action IN ('CHANGE_MAIN_LOGO','SELECT_MAIN_LOGO')")),4)

    def test_multipart_admin_ui_and_csrf_protection(self):
        admin = self.admin()
        self.client.force_login(admin)
        self.assertContains(self.client.get('/settings/'),'Hauptlogo ersetzen')
        self.assertRedirects(self.client.post('/settings/branding/',{'logo':self.image(),'reason':'Corporate Design'}),'/settings/',fetch_redirect_response=False)
        self.assertContains(self.client.get('/settings/branding/'),'Corporate Design')
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(admin)
        self.assertEqual(strict.post('/settings/branding/',{'logo':self.image(),'reason':'Ohne CSRF'}).status_code,403)

    def test_unversioned_favicon_revalidates_after_logo_change(self):
        admin = self.admin()
        replace_logo(admin,self.image('green'),'Erstes Logo')
        request = RequestFactory().get('/favicon.ico')
        first = branding.asset(request,'favicon.ico')
        tag = first['ETag']
        replace_logo(admin,self.image('red'),'Neues Logo')
        second = branding.asset(RequestFactory().get('/favicon.ico',HTTP_IF_NONE_MATCH=tag),'favicon.ico')
        self.assertEqual(second.status_code,200)
        self.assertNotEqual(second['ETag'],tag)
        unchanged = branding.asset(RequestFactory().get('/favicon.ico',HTTP_IF_NONE_MATCH=second['ETag']),'favicon.ico')
        self.assertEqual(unchanged.status_code,304)
        self.assertIn('must-revalidate',second['Cache-Control'])

    def test_invalid_image_does_not_change_current_logo(self):
        admin = self.admin()
        initial = replace_logo(admin,self.image(),'Gültig')
        with self.assertRaises(ValidationError):
            replace_logo(admin,SimpleUploadedFile('fake.png',b'bad'),'Ungültig')
        self.assertEqual(branding.branding_context()['brand_revision'],f'r{initial}')
        self.assertEqual(len(s.query('SELECT id FROM branding_revisions')),1)
