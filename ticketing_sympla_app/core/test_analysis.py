import csv
import io
import json
from unittest.mock import patch
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.db import DatabaseError, transaction
from django.core.cache import cache
from . import test_map as fixtures
from .models import Sale, SaleVersion, SalesUpload, ScenarioSnapshot, AnalysisScenario, AnalysisAlert, Statistic, Role
from .credentials import configure_client
from .management.commands.analysis_monitor import check_updates


@patch('core.cohort_search.current_year', return_value=2026)
class AnalysisTests(TestCase):
    token=fixtures.MapApiTests.token

    def setUp(self):
        cache.clear()
        fixtures.MapApiTests.setUp(self)
        self.filters={'integration_id':str(self.integration.pk),'level':'district','age_min':4,'age_max':8,'target_year':2026}

    def upload(self, rows=None, edition='2026', header=None):
        out=io.StringIO(); writer=csv.writer(out)
        writer.writerow(['sale_id','sold_on','municipality_code','tickets','revenue'])
        writer.writerows(rows or [['order-1','2026-01-01','3550308','2','100.00']])
        return self.client.post('/api/v1/sales/uploads/',{'event_id':self.event.pk,'edition':edition,
            'file':SimpleUploadedFile('sales.csv',out.getvalue().encode(),'text/csv')},**(header or self.header))

    def create(self, name='Audience research'):
        response=self.client.post('/api/v1/analysis/scenarios/',json.dumps({'name':name,'filters':self.filters,'watch':True}),content_type='application/json',**self.header)
        self.assertEqual(response.status_code,201,response.content)
        return response.json()

    def test_sales_batch_idempotency_and_correction_history(self, clock):
        first=self.upload(); self.assertEqual(first.status_code,201,first.content)
        self.assertTrue(self.upload().json()['duplicate'])
        self.assertEqual(Sale.objects.count(),1)
        response=self.upload([['order-1','2026-01-01','3550308','3','150.00']])
        self.assertEqual(response.json()['counts']['updated'],1)
        self.assertEqual(Sale.objects.get().version,2)
        self.assertEqual(SaleVersion.objects.count(),2)
        with self.assertRaises(DatabaseError),transaction.atomic():
            SaleVersion.objects.all().update(snapshot={})

    def test_invalid_csv_is_atomic_and_does_not_echo_private_content(self, clock):
        response=self.upload([['order-1','2026-01-01','','2','100.00'],['invalid@email.example','2026-01-01','','1','20.00']])
        self.assertEqual(response.status_code,400,response.content)
        self.assertNotIn('invalid@email',response.content.decode())
        self.assertEqual(Sale.objects.count(),0)
        self.assertEqual(SalesUpload.objects.count(),0)

    def test_unknown_origin_and_edition_comparison_are_explicit(self, clock):
        body=self.upload([['order-1','2026-01-01','','2','100.00']]).json()
        self.assertEqual(body['counts']['unresolved_origin'],1)
        self.upload(edition='2025')
        result=self.client.get('/api/v1/sales/summary/',{'event_id':self.event.pk},**self.header).json()
        self.assertEqual(len(result['editions']),2)
        self.assertIn('not proof',result['limitations'])

    def test_snapshot_export_and_historical_comparison(self, clock):
        scenario=self.create('<script>research</script>')
        snapshot=ScenarioSnapshot.objects.get()
        original=snapshot.result.copy()
        response=self.client.get(f"/api/v1/analysis/scenarios/{scenario['id']}/report/",{'format':'html'},**self.header)
        self.assertEqual(response.status_code,200,response.content)
        self.assertIn('<svg',response.content.decode())
        self.assertNotIn('<h1><script>',response.content.decode())
        self.assertIn('&lt;script&gt;',response.content.decode())
        self.client.post(f"/api/v1/analysis/scenarios/{scenario['id']}/snapshots/",**self.header)
        snapshots=list(ScenarioSnapshot.objects.values_list('pk',flat=True))
        result=self.client.get('/api/v1/analysis/compare/',{'snapshots':','.join(map(str,snapshots))},**self.header)
        self.assertEqual(result.status_code,200,result.content)
        self.assertEqual(len(result.json()['results']),2)
        snapshot.refresh_from_db(); self.assertEqual(snapshot.result,original)
        with self.assertRaises(DatabaseError),transaction.atomic():
            ScenarioSnapshot.objects.all().delete()

    def test_watch_alerts_are_local_and_deduplicated(self, clock):
        self.create()
        self.assertEqual(check_updates(),0)
        self.upload()
        self.assertEqual(check_updates(),1)
        self.assertEqual(check_updates(),0)
        self.assertEqual(AnalysisAlert.objects.count(),1)

    def test_tenant_and_permission_boundaries(self, clock):
        scenario=self.create()
        other=configure_client('analysis-other','OtherPass1!')
        header=self.token(other)
        self.assertEqual(self.upload(header=header).status_code,403)
        self.assertEqual(self.client.get('/api/v1/analysis/scenarios/',**header).status_code,403)
        from .rbac import PERMISSIONS
        role=Role.objects.create(name='Analysis test reader'); role.permissions.set(list(PERMISSIONS)); other.role=role; other.save()
        self.assertEqual(self.client.get(f"/api/v1/analysis/scenarios/{scenario['id']}/report/",**header).status_code,404)
        self.assertEqual(self.client.get('/api/v1/sales/uploads/',**header).json()['count'],0)

    def test_opportunities_never_label_missing_uploads_as_zero_demand(self, clock):
        scenario=self.create()
        response=self.client.get(f"/api/v1/analysis/scenarios/{scenario['id']}/opportunities/",{'event_id':self.event.pk},**self.header)
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(response.json()['uploaded_records'],0)
        self.assertTrue(all(row['evidence']=='no_uploaded_sales_record' for row in response.json()['results']))

    def test_bbox_and_proposed_venue_filters(self, clock):
        response=self.client.get('/api/v1/demographics/map/',{**self.filters,'bbox':'-46.7,-23.6,-46.6,-23.5'},**self.header)
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(response.json()['count'],1)
        response=self.client.get('/api/v1/demographics/map/',{**self.filters,'venue_lat':-23.55,'venue_lon':-46.63,'radius_km':10},**self.header)
        self.assertEqual(response.json()['count'],1)
        self.assertEqual(response.json()['event']['name'],'Proposed venue')

    def test_cohort_cache_is_invalidated_after_version_changes(self, clock):
        url='/api/v1/demographics/map/'
        before=self.client.get(url,self.filters,**self.header).json()['results']
        Statistic.objects.filter(category__code='0_4').update(value=999,version=2)
        after=self.client.get(url,self.filters,**self.header).json()['results']
        self.assertNotEqual([row['exact_count'] for row in before],[row['exact_count'] for row in after])

    def test_sales_evidence_in_report_is_rechecked_after_permission_revocation(self, clock):
        self.upload()
        self.filters['event_id']=self.event.pk
        scenario=self.create()
        self.assertIn('uploaded_sales',ScenarioSnapshot.objects.get().result)
        role=Role.objects.create(name='Restricted historical reporter')
        role.permissions.set(['scenarios:read','reports:read','demographics:read','events:read'])
        self.api_account.is_superuser=False;self.api_account.role=role;self.api_account.save()
        response=self.client.get(f"/api/v1/analysis/scenarios/{scenario['id']}/report/",**self.header)
        self.assertEqual(response.status_code,403,response.content)
