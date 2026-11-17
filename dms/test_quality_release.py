from django.test import TestCase
from django.db import connection,DatabaseError,transaction
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.utils import timezone
import io,json
from . import tests as fixtures,services as s
from .simple_workflow import upload_document,release_own_qmb_document
from django.core.files.uploadedfile import SimpleUploadedFile


class QualityReleaseTests(TestCase):
    setUp=fixtures.WorkflowTests.setUp
    enable_runtime_role=fixtures.WorkflowTests.enable_runtime_role

    def test_qmb_release_is_guarded_and_immutable(self):
        with self.assertRaises(DatabaseError),transaction.atomic():
            s.query('SELECT release_qmb_document(%s,%s,%s)',[s.actor(self.author),self.vid,s.fingerprint(s.get_version(self.author,self.vid)[1])])
        with self.assertRaises(PermissionDenied):release_own_qmb_document(self.reviewer,self.vid)
        data={'number':'QMB-AUTO','document_type':'Arbeitsanweisung','department':self.dep,'title':'Direktfreigabe','effective_from':timezone.now(),'change_summary':''}
        self.enable_runtime_role()
        vid=upload_document(self.reviewer,data,SimpleUploadedFile('auto.txt',b'QMB contents'))
        self.assertEqual(s.get_version(self.reader,vid)[1]['status'],'APPROVED')
        self.assertEqual(s.query('SELECT content_fingerprint FROM qmb_direct_releases WHERE version_id=%s',[vid])[0]['content_fingerprint'],s.fingerprint(s.get_version(self.reviewer,vid)[1]))
        with self.assertRaises(DatabaseError),transaction.atomic():s.query('DELETE FROM qmb_direct_releases WHERE version_id=%s',[vid])
        revision=s.new_revision(self.reviewer,vid,'minor','Korrektur')
        release_own_qmb_document(self.reviewer,revision)
        self.assertEqual(s.get_version(self.reader,revision)[1]['status'],'APPROVED')

    def test_catalog_uses_one_result_query_and_plan_can_be_measured(self):
        self.client.force_login(self.author);captured=[]
        def capture(execute,sql,params,many,context):
            if sql.lstrip().startswith('WITH input AS'):captured.append(sql)
            return execute(sql,params,many,context)
        with connection.execute_wrapper(capture):self.assertEqual(self.client.get('/documents/').status_code,200)
        self.assertEqual(len(captured),1)
        html=self.client.get('/documents/').content.decode()
        self.assertLess(html.index('/assets/ui/catalog-state.js'),html.index('/assets/ui/catalog.js'))
        self.assertEqual(self.client.get('/documents/',{'page':'9'*100}).status_code,200)
        output=io.StringIO();call_command('profile_catalog',self.author.username,stdout=output)
        self.assertGreaterEqual(json.loads(output.getvalue())['execution_ms'],0)
