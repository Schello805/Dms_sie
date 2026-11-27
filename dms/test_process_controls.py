from datetime import date, timedelta
from decimal import Decimal
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, transaction
from django.test import TestCase
from . import tests as fixtures, services as s, processes
from . import process_controls as controls


class ProcessControlTests(TestCase):
    setUp = fixtures.WorkflowTests.setUp
    enable_runtime_role = fixtures.WorkflowTests.enable_runtime_role

    def root(self):
        return processes.save(self.reviewer,None,None,'CONTROL',dict(title='Kontrollprozess',description='Beschreibung',owner_id=s.actor(self.author),documents=[],references=[]),True,True,'')

    def risk(self):
        return dict(title='Lieferausfall',description='Lieferant fällt aus',owner_id=s.actor(self.author),probability=3,impact=5,action='Alternative qualifizieren',due_on=(date.today()-timedelta(days=1)).isoformat(),status='progress',residual_probability=1,residual_impact=5,effectiveness='')

    def kpi(self):
        return dict(title='Energieintensität',description='Verbrauch / Stückzahl',source='Zähler und ERP',owner_id=s.actor(self.author),unit='kWh/Stück',direction='lte',target='12.5',interval_months=1,first_due=date.today().isoformat())

    def test_runtime_risk_history_and_optimistic_lock(self):
        self.enable_runtime_role()
        process=self.root();risk=self.risk()
        identifier=controls.save(self.reviewer,process,None,'risk',risk,True,0,'')
        row=controls.controls(self.reviewer,process)[0]
        self.assertEqual((row['score'],row['band'],row['residual_score'],row['overdue']),(15,'Hoch',5,True))
        changed={**risk,'title':'Neuer Titel'}
        controls.save(self.reviewer,process,identifier,'risk',changed,False,1,'')
        with self.assertRaises(ValidationError):controls.save(self.reviewer,process,identifier,'risk',risk,True,1,'')
        self.assertEqual(len(s.query('SELECT * FROM process_control_history')),2)
        self.assertFalse(controls.controls(self.reviewer,process)[0]['active'])
        with self.assertRaises(DatabaseError),transaction.atomic():s.query('DELETE FROM process_control_history')
        with self.assertRaises(DatabaseError),transaction.atomic():s.query('UPDATE process_controls SET active=true')

    def test_measurements_corrections_and_frozen_target(self):
        self.enable_runtime_role()
        process=self.root();definition=self.kpi()
        identifier=controls.save(self.reviewer,process,None,'kpi',definition,True,0,'')
        day=date.today()-timedelta(days=40)
        controls.measure(self.reviewer,identifier,day,Decimal('10.25'),'',1)
        row=controls.controls(self.reviewer,process)[0]
        self.assertTrue(row['met']);self.assertTrue(row['overdue'])
        controls.measure(self.reviewer,identifier,day,Decimal('11'),'',1)
        controls.measure(self.reviewer,identifier,day,Decimal('13'),'Zählerstand korrigiert',1)
        self.assertFalse(controls.controls(self.reviewer,process)[0]['met'])
        controls.save(self.reviewer,process,identifier,'kpi',{**definition,'target':'20','unit':'MWh/Stück'},True,1,'')
        row=controls.controls(self.reviewer,process)[0]
        self.assertFalse(row['met']);self.assertTrue(row['definition_changed'])
        self.assertEqual(row['measured_unit'],'kWh/Stück')
        with self.assertRaises(ValidationError):controls.measure(self.reviewer,identifier,date.today(),Decimal('9'),'',1)
        with self.assertRaises(ValidationError):controls.measure(self.reviewer,identifier,date.today()+timedelta(days=1),Decimal('9'),'',2)
        with self.assertRaises(DatabaseError),transaction.atomic():s.query('UPDATE process_measurements SET value=0')
        self.client.force_login(self.reviewer)
        page=self.client.get(f'/processes/{process}/measurements/{identifier}/')
        self.assertContains(page,'Korrigierter Altwert')
        self.assertContains(page,'Zählerstand korrigiert')

    def test_permissions_and_public_process_does_not_leak_internal_data(self):
        process=self.root();identifier=controls.save(self.reviewer,process,None,'risk',self.risk(),True,0,'')
        self.assertNotContains(self.client.get(f'/processes/{process}/'),'Lieferausfall')
        self.assertEqual(self.client.get(f'/processes/{process}/controls/').status_code,302)
        for user in (self.reader,self.author,self.approver):
            with self.assertRaises(PermissionDenied):controls.save(user,process,None,'risk',self.risk(),True,0,'')
            with self.assertRaises(PermissionDenied):controls.controls(user,process)
            self.client.force_login(user)
            self.assertEqual(self.client.get(f'/processes/{process}/controls/').status_code,403)
        self.client.force_login(self.reviewer)
        self.assertContains(self.client.get(f'/processes/{process}/controls/'),'Lieferausfall')
        other=processes.save(self.reviewer,None,None,'OTHER',dict(title='Anderer Prozess',description='Test',owner_id=s.actor(self.author)),True,True,'')
        self.assertEqual(self.client.get(f'/processes/{other}/controls/risk/{identifier}/edit/').status_code,404)
        with self.assertRaises(ValidationError):controls.save(self.reviewer,other,identifier,'risk',self.risk(),True,1,'')

    def test_web_validation_and_deactivation(self):
        process=self.root()
        self.client.force_login(self.reviewer)
        data=self.risk();data.update(active='on',revision=0,status='closed',residual_probability='',residual_impact='')
        response=self.client.post(f'/processes/{process}/controls/risk/new/',data)
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Für Abschluss oder Akzeptanz')
        data['effectiveness']='Wirksamkeit nachgewiesen'
        response=self.client.post(f'/processes/{process}/controls/risk/new/',data)
        self.assertEqual(response.status_code,302)
        data=self.kpi();data.update(active='on',revision=0)
        response=self.client.post(f'/processes/{process}/controls/kpi/new/',data)
        self.assertEqual(response.status_code,302)
        kpi=next(i for i in controls.controls(self.reviewer,process) if i['kind']=='kpi')
        response=self.client.post(f'/processes/{process}/measurements/{kpi["id"]}/',{'measured_on':date.today().isoformat(),'value':'12','note':'','revision':1})
        self.assertEqual(response.status_code,302)
        processes.save(self.reviewer,process,None,'CONTROL',dict(title='Kontrollprozess',description='Beschreibung',owner_id=s.actor(self.author)),False,False,'')
        with self.assertRaises(ValidationError):controls.measure(self.reviewer,kpi['id'],date.today(),Decimal('12'),'Correction',1)
        with self.assertRaises(ValidationError):controls.save(self.reviewer,process,None,'risk',self.risk(),True,0,'')
