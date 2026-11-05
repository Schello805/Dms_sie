from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied,ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError,transaction
from django.test import TestCase
from django.utils import timezone
from . import tests as fixtures,services as s,masterdata as m,storage
from .forms import DocumentForm,EditForm


class MasterDataTests(TestCase):
    setUp=fixtures.WorkflowTests.setUp
    publish=fixtures.WorkflowTests.publish
    enable_runtime_role=fixtures.WorkflowTests.enable_runtime_role

    def admin(self):
        user=get_user_model().objects.create_user('master-it',password='TestPassword-2026!')
        s.query("INSERT INTO users(auth_user_id,display_name,settings_admin) VALUES (%s,'Master IT',true)",[user.pk])
        return user

    def save(self,kind,data,target=None,user=None):
        return m.save(user or self.reviewer,kind,target,dict(active=True,reason='Geprüfte Stammdatenpflege',**data))

    def category(self):
        return self.save('categories',{'name':'Eigene Kategorie','review_interval_months':18,'retention_months':60,'storage_location_id':1})

    def reference(self):
        standard=self.save('standards',{'name':'Betriebliche Norm','edition':'2026'})
        reference=self.save('references',{'standard_id':standard,'reference':'7.5','label':'Gelenkte Dokumente'})
        return standard,reference

    def test_category_rename_preserves_frozen_document_key_and_soft_delete_preserves_reading(self):
        cid=self.category()
        key=s.query('SELECT name FROM document_categories WHERE id=%s',[cid])[0]['name']
        vid=s.create_document(self.author,dict(number='CAT-001',title='Kategorie-Test',document_type=key,department=self.dep,change_summary='Erstfassung',effective_from=timezone.now()))
        storage.upload(self.author,vid,SimpleUploadedFile('category.txt',b'Kategorie-Test'))
        s.transition(self.author,vid,'submit','Einreichen');s.transition(self.reviewer,vid,'accept','Geprüft');s.transition(self.reviewer,vid,'accept','Freigegeben')
        before=s.fingerprint(s.get_version(self.author,vid)[1])
        data=m.get('categories',cid);data.update(name='Umbenannte Kategorie',reason='Neue Bezeichnung')
        m.save(self.reviewer,'categories',cid,data)
        self.assertEqual(s.get_version(self.reader,vid)[1]['document_type'],key)
        self.assertEqual(s.get_version(self.reader,vid)[1]['category_label'],'Umbenannte Kategorie')
        self.assertEqual(before,s.fingerprint(s.get_version(self.author,vid)[1]))
        data['active']=False;m.save(self.reviewer,'categories',cid,data)
        self.assertEqual(s.get_version(self.reader,vid)[1]['status'],'APPROVED')
        self.assertNotIn(key,dict(DocumentForm(user=self.author).fields['document_type'].choices))
        with self.assertRaises(ValidationError):s.create_document(self.author,dict(number='NO-CAT',title='X',document_type=key,department=self.dep,change_summary='X',effective_from=timezone.now()))

    def test_departments_support_edit_deactivate_reactivate_and_cycle_guard(self):
        a=self.save('departments',{'name':'Fertigung','code':'FERT','parent_id':None})
        b=self.save('departments',{'name':'Montage','code':'MONT','parent_id':a})
        data=m.get('departments',a);data.update(parent_id=b,reason='Nicht erlaubt')
        with self.assertRaises(ValidationError):m.save(self.reviewer,'departments',a,data)
        self.assertIsNone(m.get('departments',a)['parent_id'])
        data.update(parent_id=None,active=False,name='Fertigung neu');m.save(self.reviewer,'departments',a,data)
        self.assertFalse(m.get('departments',a)['active'])
        self.assertNotIn(a,dict(DocumentForm(user=self.author).fields['department'].choices))
        data['active']=True;m.save(self.reviewer,'departments',a,data)
        self.assertTrue(m.get('departments',a)['active']);self.assertEqual(m.get('departments',b)['parent_id'],a)

    def test_storage_location_cannot_be_disabled_while_active_categories_use_it(self):
        data=m.get('locations',1);data.update(active=False,reason='Nicht erlaubt')
        with self.assertRaises(ValidationError):m.save(self.reviewer,'locations',1,data)
        location=self.save('locations',{'name':'Zusätzliche Ablage','description':'Logischer Ort'})
        data=m.get('locations',location);data.update(name='Ablage neu',active=False,reason='Stilllegung')
        m.save(self.reviewer,'locations',location,data)
        self.assertFalse(m.get('locations',location)['active'])
        self.assertEqual(m.get('locations',location)['name'],'Ablage neu')

    def test_used_standard_and_reference_are_immutable_but_can_be_deactivated(self):
        standard,reference=self.reference()
        v=s.get_version(self.author,self.vid)[1]
        s.edit_draft(self.author,self.vid,dict(title=v['title'],change_summary='Normzuordnung',effective_from=v['effective_from'],standard_references=[reference]))
        self.publish()
        data=m.get('references',reference);data.update(label='Ungeprüfte Umdeutung',reason='Nicht zulässig')
        with self.assertRaises(ValidationError):m.save(self.reviewer,'references',reference,data)
        data=m.get('standards',standard);data.update(edition='2027',reason='Nicht zulässig')
        with self.assertRaises(ValidationError):m.save(self.reviewer,'standards',standard,data)
        data=m.get('references',reference);data.update(active=False,reason='Neue Zuordnung sperren');m.save(self.reviewer,'references',reference,data)
        revision=s.new_revision(self.author,self.vid,reason='Überarbeitung mit bisheriger Referenz')
        draft=s.get_version(self.author,revision)[1]
        s.edit_draft(self.author,revision,dict(title='Neuer Titel',change_summary='Korrektur',effective_from=draft['effective_from'],standard_references=[reference]))
        self.assertTrue(s.query('SELECT 1 FROM version_standard_links WHERE version_id=%s AND reference_id=%s',[revision,reference]))
        self.assertNotIn(reference,dict(DocumentForm(user=self.author).fields['standard_references'].choices))
        form=EditForm(initial={'standard_references':[reference]})
        self.assertIn(reference,dict(form.fields['standard_references'].choices))

    def test_submitted_reference_remains_protected_after_return_and_mapping_removal(self):
        standard,reference=self.reference()
        v=s.get_version(self.author,self.vid)[1]
        data=dict(title=v['title'],change_summary='Referenz prüfen',effective_from=v['effective_from'],standard_references=[reference])
        s.edit_draft(self.author,self.vid,data)
        s.transition(self.author,self.vid,'submit','Prüfung')
        s.transition(self.reviewer,self.vid,'return','Änderung erforderlich')
        data['standard_references']=[];s.edit_draft(self.author,self.vid,data)
        self.assertFalse(s.query('SELECT 1 FROM version_standard_links WHERE reference_id=%s',[reference]))
        protected=m.get('references',reference);protected.update(label='Nachträglich umdeuten',reason='Nicht zulässig')
        with self.assertRaises(ValidationError):m.save(self.reviewer,'references',reference,protected)
        self.assertTrue(s.query('SELECT 1 FROM standard_reference_usage WHERE reference_id=%s',[reference]))

    def test_group_ui_adds_and_removes_grants_and_profile_ui_updates_contacts(self):
        admin=self.admin();self.client.force_login(admin)
        response=self.client.post('/management/master/groups/new/',{'name':'UI Gruppe','members':[s.actor(self.reader)],'active':'on','reason':'Gruppenanlage'})
        group=s.query("SELECT id FROM dms_groups WHERE name='UI Gruppe'")[0]['id']
        self.assertRedirects(response,f'/management/master/groups/{group}/')
        url=f'/management/master/groups/{group}/'
        self.client.post(url,{'operation':'grant','grant-role':'AUTHOR','grant-department_id':self.dep,'grant-document_number':'','grant-reason':'Aufgabe zuweisen'})
        self.assertTrue(s.allowed(s.actor(self.reader),self.dep,'AUTHOR'))
        assignment=s.query("SELECT id FROM role_assignments WHERE group_id=%s AND role='AUTHOR'",[group])[0]['id']
        self.client.post(url,{'operation':'revoke','assignment_id':assignment,'reason':'Aufgabe beendet'})
        self.assertFalse(s.allowed(s.actor(self.reader),self.dep,'AUTHOR'))
        response=self.client.post(url,{'operation':'grant','grant-role':'AUTHOR','grant-department_id':'','grant-document_number':'NOT-EXISTING','grant-reason':'Unbekannt'})
        self.assertContains(response,'Dokumentnummer existiert nicht')
        uid=s.actor(self.reader)
        self.client.post(f'/settings/users/{uid}/profile/',{'display_name':'Leserprofil neu','email':'profile@example.test','reason':'Kontaktdaten'})
        self.assertEqual(get_user_model().objects.get(pk=self.reader.pk).email,'profile@example.test')

    def test_legacy_admin_group_cannot_be_rewired_in_the_web(self):
        admin=self.admin()
        group=s.query("INSERT INTO dms_groups(name) VALUES ('Historische Admin-Gruppe') RETURNING id")[0]['id']
        s.query("INSERT INTO role_assignments(group_id,role) VALUES (%s,'ADMIN')",[group])
        s.query('INSERT INTO group_memberships(group_id,user_id) VALUES (%s,%s)',[group,s.actor(admin)])
        data=m.get('groups',group);data.update(members=[s.actor(self.reader)],active=False,reason='Nicht zulässig')
        self.enable_runtime_role()
        with self.assertRaises(ValidationError):m.save(admin,'groups',group,data)
        self.assertEqual(m.get('groups',group)['members'],[s.actor(admin)])
        self.assertTrue(m.get('groups',group)['active'])

    def test_permissions_and_runtime_role_cannot_directly_modify_master_tables(self):
        admin=self.admin();self.enable_runtime_role()
        with self.assertRaises(PermissionDenied):self.save('departments',{'name':'Nicht QMB','code':'NO','parent_id':None},user=admin)
        with self.assertRaises(PermissionDenied):self.save('groups',{'name':'Nicht IT','members':[]})
        cid=self.category();self.assertTrue(cid)
        key=s.query('SELECT name FROM document_categories WHERE id=%s',[cid])[0]['name']
        created=s.create_document(self.author,dict(number='RUNTIME-MASTER',title='Aktive Stammdaten',document_type=key,department=self.dep,change_summary='Runtime-Test',effective_from=timezone.now()))
        self.assertTrue(created)
        for statement in ("UPDATE departments SET name='Direkt' WHERE id=1","INSERT INTO dms_groups(name) VALUES ('Direkt')","INSERT INTO standards(name,edition) VALUES ('Direkt','1')"):
            with self.assertRaises(DatabaseError):
                with transaction.atomic():s.query(statement)

    def test_group_membership_grants_revocation_and_deactivation_apply_immediately(self):
        admin=self.admin();self.enable_runtime_role()
        group=self.save('groups',{'name':'Autoren-Gruppe','members':[s.actor(self.reader)]},user=admin)
        m.grant(admin,group,'AUTHOR',self.dep,'','Führungskraft zugeordnet')
        self.assertTrue(s.allowed(s.actor(self.reader),self.dep,'AUTHOR'))
        assignment=s.query("SELECT id FROM role_assignments WHERE group_id=%s AND role='AUTHOR'",[group])[0]['id']
        m.revoke(admin,group,assignment,'Aufgabe beendet')
        self.assertFalse(s.allowed(s.actor(self.reader),self.dep,'AUTHOR'))
        m.grant(admin,group,'AUTHOR',self.dep,'','Erneut zugeordnet')
        data=m.get('groups',group);data.update(active=False,reason='Gruppe stilllegen');m.save(admin,'groups',group,data)
        self.assertFalse(s.allowed(s.actor(self.reader),self.dep,'AUTHOR'))
        data['active']=True;m.save(admin,'groups',group,data)
        self.assertTrue(s.allowed(s.actor(self.reader),self.dep,'AUTHOR'))
        data['members']=[];m.save(admin,'groups',group,data)
        self.assertFalse(s.allowed(s.actor(self.reader),self.dep,'AUTHOR'))
        with self.assertRaises(ValidationError):m.grant(admin,group,'ADMIN',None,'','Nicht erlaubt')

    def test_profile_edit_syncs_email_but_does_not_change_login_or_roles(self):
        admin=self.admin();self.enable_runtime_role();uid=s.actor(self.author)
        s.query('SELECT update_ims_profile(%s,%s,%s,%s,%s)',[s.actor(admin),uid,'Neuer Name','new@example.test','Stammdaten aktualisiert'])
        self.assertEqual(s.query('SELECT display_name,email FROM users WHERE id=%s',[uid])[0],{'display_name':'Neuer Name','email':'new@example.test'})
        self.assertEqual(get_user_model().objects.get(pk=self.author.pk).username,'author')
        self.assertEqual(get_user_model().objects.get(pk=self.author.pk).email,'new@example.test')
        self.assertTrue(s.allowed(uid,self.dep,'AUTHOR'))
        with self.assertRaises(DatabaseError):
            with transaction.atomic():s.query('SELECT update_ims_profile(%s,%s,%s,%s,%s)',[s.actor(self.reviewer),uid,'Falsch','bad@example.test','Nicht IT'])

    def test_management_pages_create_update_soft_deactivate_and_role_boundaries(self):
        admin=self.admin();self.client.force_login(self.reviewer)
        for kind in ('categories','departments','locations','standards','references'):
            self.assertEqual(self.client.get(f'/management/master/{kind}/').status_code,200)
            self.assertEqual(self.client.get(f'/management/master/{kind}/new/').status_code,200)
        self.assertEqual(self.client.get('/management/master/groups/').status_code,403)
        response=self.client.post('/management/master/departments/new/',{'name':'Service','code':'SERV','parent_id':'','active':'on','reason':'Neue Abteilung'})
        self.assertRedirects(response,'/management/master/departments/')
        target=s.query("SELECT id FROM departments WHERE code='SERV'")[0]['id']
        self.client.get(f'/management/master/departments/{target}/?action=deactivate')
        self.assertTrue(m.get('departments',target)['active'])
        self.client.post(f'/management/master/departments/{target}/',{'name':'Service neu','code':'SERV','parent_id':'','reason':'Stilllegung'})
        self.assertFalse(m.get('departments',target)['active'])
        self.client.force_login(admin)
        self.assertEqual(self.client.get('/management/master/groups/').status_code,200)
        self.assertEqual(self.client.get('/management/master/categories/').status_code,403)
        self.assertEqual(self.client.get(f'/settings/users/{s.actor(self.reader)}/profile/').status_code,200)
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get('/management/master/departments/').status_code,403)
