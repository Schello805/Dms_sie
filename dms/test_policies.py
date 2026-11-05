from datetime import date,timedelta
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import DatabaseError,transaction
from django.test import TestCase,Client
from django.utils import timezone
from . import tests as fixtures,services as s,policies

class ReviewPolicyTests(TestCase):
    setUp = fixtures.WorkflowTests.setUp
    publish = fixtures.WorkflowTests.publish
    enable_runtime_role = fixtures.WorkflowTests.enable_runtime_role

    def admin(self):
        user = get_user_model().objects.create_user('settings-test',password='TestPassword-2026!')
        s.query("INSERT INTO users(display_name,auth_user_id,settings_admin,qmb_role) VALUES ('IMS-Admin',%s,false,'DEPUTY')",[user.pk])
        return user

    def intervals(self):
        return {r['id']:r['review_interval_months'] for r in s.query('SELECT * FROM document_categories')}

    def test_default_is_two_calendar_years_and_handles_leap_days(self):
        self.assertEqual(policies.interval_for('Richtlinie'),24)
        self.assertEqual(policies.add_months(date(2024,2,29),24),date(2026,2,28))
        self.assertEqual(policies.add_months(date(2026,1,31),1),date(2026,2,28))
        effective = timezone.make_aware(__import__('datetime').datetime(2024,2,29,12))
        vid = s.create_document(self.author,dict(number='DEFAULT-001',document_type='Prozess',department=self.dep,title='Standardfrist',change_summary='Erstfassung',effective_from=effective))
        self.assertEqual(s.get_version(self.author,vid)[1]['next_review_on'],date(2026,2,28))

    def test_successful_review_automatically_renews_validity_and_shows_last_review(self):
        self.publish()
        initial = s.get_version(self.author,self.vid)[1]['next_review_on']
        rid = s.record_review(self.reviewer,self.vid,'UNCHANGED','Inhalt auf Richtigkeit geprüft')
        row = s.query('SELECT * FROM periodic_reviews WHERE id=%s',[rid])[0]
        self.assertEqual(row['next_review_on'],policies.add_months(timezone.localdate(),24))
        self.assertEqual(row['review_interval_months'],24)
        version = s.visible_versions(self.author)[0]
        self.assertEqual(version['last_review_on'],timezone.localdate())
        self.assertEqual(version['review_due_on'],row['next_review_on'])
        self.assertFalse(version['review_overdue'])
        self.assertEqual(s.get_version(self.author,self.vid)[1]['next_review_on'],initial)

    def test_category_change_is_audited_and_not_retroactive(self):
        self.publish()
        before = s.visible_versions(self.author)[0]['review_due_on']
        fingerprint = s.fingerprint(s.get_version(self.author,self.vid)[1])
        admin = self.admin()
        intervals = self.intervals()
        category = s.query("SELECT id FROM document_categories WHERE name='Richtlinie'")[0]['id']
        intervals[category] = 36
        policies.save_intervals(admin,intervals,'Prüffrist für Richtlinien angepasst')
        self.assertEqual(s.visible_versions(self.author)[0]['review_due_on'],before)
        self.assertEqual(s.fingerprint(s.get_version(self.author,self.vid)[1]),fingerprint)
        s.record_review(self.reviewer,self.vid,'UNCHANGED','Erneut geprüft')
        self.assertEqual(s.visible_versions(self.author)[0]['review_due_on'],policies.add_months(timezone.localdate(),36))
        self.assertTrue(s.query("SELECT 1 FROM audit_events WHERE action='CHANGE_REVIEW_POLICY'"))

    def test_unsuccessful_review_does_not_extend_validity(self):
        due = timezone.localdate()-timedelta(days=1)
        s.query('UPDATE document_versions SET next_review_on=%s WHERE id=%s',[due,self.vid])
        self.publish()
        s.record_review(self.reviewer,self.vid,'REVISION_REQUIRED','Inhalt stimmt nicht mehr',timezone.localdate()+timedelta(days=30))
        version = s.visible_versions(self.author)[0]
        self.assertEqual(version['review_due_on'],due)
        self.assertEqual(version['last_review_on'],timezone.localdate())
        self.assertTrue(version['review_overdue'])
        self.assertEqual(len(s.visible_versions(self.author,due_only=True)),1)

    def test_only_explicit_settings_admin_can_edit_and_csrf_is_required(self):
        for user in [self.author,self.approver,self.reader]:
            self.client.force_login(user)
            self.assertEqual(self.client.get('/management/').status_code,403)
            self.assertEqual(self.client.post('/management/',{}).status_code,403)
        admin = self.admin()
        self.client.force_login(admin)
        self.assertContains(self.client.get('/management/'),'24 Monate (2 Jahre)')
        self.assertContains(self.client.get('/management/'),'Richtlinie')
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(admin)
        self.assertEqual(csrf.post('/management/',{}).status_code,403)
        with self.assertRaises(PermissionDenied):
            policies.save_intervals(self.author,self.intervals(),'Nicht erlaubt')

    def test_admin_ui_saves_category_settings_with_runtime_role(self):
        admin = self.admin()
        self.enable_runtime_role()
        self.client.force_login(admin)
        data = {f'category_{key}':value for key,value in self.intervals().items()}
        category = s.query("SELECT id FROM document_categories WHERE name='Vorlage'")[0]['id']
        data[f'category_{category}'] = 12
        for c in s.query('SELECT id,storage_location_id FROM document_categories'):
            data[f"location_{c['id']}"] = c['storage_location_id']
        data['reason'] = 'Vorlagen jährlich prüfen'
        self.assertEqual(self.client.post('/management/',data).status_code,302)
        self.assertEqual(policies.interval_for('Vorlage'),12)
        with self.assertRaises(DatabaseError),transaction.atomic():
            s.query('UPDATE users SET settings_admin=true')

    def test_review_endpoint_uses_category_and_ignores_forged_date(self):
        self.publish()
        self.client.force_login(self.reviewer)
        response = self.client.post(f'/versions/{self.vid}/review/',{'result':'UNCHANGED','rationale':'Richtigkeit bestätigt','next_review_on':'2099-01-01'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(s.visible_versions(self.reviewer)[0]['review_due_on'],policies.add_months(timezone.localdate(),24))
        self.assertContains(self.client.get('/'),'Letztes Review')
        self.assertContains(self.client.get('/'),'Gültig bis / Review fällig')
        self.assertContains(self.client.get('/'),timezone.localdate().strftime('%d.%m.%Y'))

    def test_invalid_intervals_and_longer_review_overrides_are_rejected(self):
        admin = self.admin()
        for invalid in [0,-1,1201,True]:
            intervals = self.intervals()
            intervals[next(iter(intervals))] = invalid
            with self.assertRaises(ValidationError):
                policies.save_intervals(admin,intervals,'Ungültiger Testwert')
        self.publish()
        with self.assertRaises(ValidationError):
            s.record_review(self.reviewer,self.vid,'UNCHANGED','Zu lange Frist',policies.add_months(timezone.localdate(),25))
