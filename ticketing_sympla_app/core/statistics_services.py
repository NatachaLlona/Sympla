"""Atomic relational persistence for demographic statistics and immutable lineage."""
import hashlib
import json
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from .models import (Coordinator, SyncRun, ApiUser, Integration, Geography, StatisticalIndicator,
    StatisticalCategory, Statistic, StatisticVersion, ImportSource, StatisticObservation, DataCoverage)
from .connectors import connector_for
from .rbac import permitted
from .sync_exception import SyncError
from .integration_modules.ibge.catalog import INDICATORS, AGE_BANDS
from .services import audit


def seed_catalog():
    for code, (name, unit, universe) in INDICATORS.items():
        indicator, _ = StatisticalIndicator.objects.get_or_create(code=code, defaults={'name': name, 'unit': unit, 'universe': universe})
        categories = AGE_BANDS + [('total', 'Population covered by age tabulation', None, None, 'V01006')] if code == 'age_population' else [('total', 'Total', None, None, None)]
        for category, label, age_min, age_max, _ in categories:
            StatisticalCategory.objects.get_or_create(indicator=indicator, code=category,
                defaults={'name': label, 'age_min': age_min, 'age_max': age_max})


def geography_for(data, cache):
    key = (data['level'], data['code'])
    if key not in cache:
        parent = geography_for(data['parent'], cache) if data.get('parent') else None
        expected_parent = {'state': None, 'city': 'state', 'neighborhood': 'city', 'district': 'city'}
        if data['level'] not in expected_parent or (parent.level if parent else None) != expected_parent[data['level']]:
            raise SyncError('ibge_invalid_response')
        location, created = Geography.objects.get_or_create(level=data['level'], code=data['code'], reference_year=2022,
            defaults={'name': data['name'], 'parent': parent})
        if not created and location.parent_id != (parent.pk if parent else None):
            raise SyncError('ibge_invalid_response')
        cache[key] = location
    return cache[key]


@transaction.atomic
def persist_statistics(run_id, batch):
    Coordinator.objects.select_for_update().get(pk=1)
    run = SyncRun.objects.select_for_update().get(pk=run_id, status='running')
    owner = ApiUser.objects.select_for_update().get(pk=run.owner_id)
    integration = Integration.objects.select_for_update().get(pk=run.integration_id)
    if not permitted(owner, 'synchronization:write'):
        raise SyncError('owner_authorization_changed')
    if integration.owner_id != owner.pk or not integration.active or integration.deleted_at or integration.revision != run.integration_revision or connector_for(integration.provider).version != run.connector_version:
        raise SyncError('integration_changed')
    seed_catalog()
    collected_at = timezone.now()
    sources = {}
    for item in batch['sources']:
        sources[item['code']] = ImportSource.objects.create(run=run, code=item['code'], url=item['url'], sha256=item['sha256'], reference_period='2022', collected_at=collected_at)
    locations, seen = {}, set()
    categories = {(row.indicator_id, row.code): row for row in StatisticalCategory.objects.select_related('indicator')}
    counts = {'received': len(batch['records']), 'created': 0, 'updated': 0, 'unchanged': 0, 'missing': 0}
    for item in batch['records']:
        category = categories[(item['indicator'], item['category'])]
        geography = geography_for(item['geography'], locations)
        key = (geography.pk, category.pk, '2022')
        if key in seen:
            raise SyncError('ibge_invalid_response')
        seen.add(key)
        snapshot = {'value': item['value'], 'source_status': item['source_status']}
        digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
        statistic, created = Statistic.objects.get_or_create(integration=integration, geography=geography, category=category, period='2022',
            defaults={'value': Decimal(item['value']) if item['value'] is not None else None, 'source_status': item['source_status'], 'fingerprint': digest, 'last_run': run})
        if created or statistic.fingerprint != digest:
            if not created:
                statistic.version += 1
            statistic.value = Decimal(item['value']) if item['value'] is not None else None
            statistic.source_status, statistic.fingerprint = item['source_status'], digest
            version = StatisticVersion.objects.create(statistic=statistic, version=statistic.version,
                value=statistic.value, source_status=statistic.source_status, fingerprint=digest, run=run)
            audit(run.actor, 'statistic.created' if created else 'statistic.updated', 'statistic', statistic.pk,
                {'integration_id': str(integration.pk), 'geography_code': geography.code, 'indicator': category.indicator_id,
                 'category': category.code, 'value': item['value'], 'source_status': item['source_status']}, run.pk, owner=owner)
            counts['created' if created else 'updated'] += 1
        else:
            version = StatisticVersion.objects.get(statistic=statistic, version=statistic.version)
            counts['unchanged'] += 1
        statistic.last_seen_at, statistic.last_run = collected_at, run
        statistic.save()
        StatisticObservation.objects.create(statistic=statistic, statistic_version=version, source=sources[item['source']],
            run=run, source_columns=item['source_columns'], transformation_version=run.connector_version, collected_at=collected_at)
        if statistic.value is None:
            counts['missing'] += 1
    coverage = batch['coverage']
    for item in coverage:
        DataCoverage.objects.create(run=run, **item)
    partial = any(item['status'] != 'available' for item in coverage) or bool(counts['missing'])
    run.status, run.running_slot = ('partial' if partial else 'success'), None
    run.finished_at, run.collected_at, run.counts = timezone.now(), collected_at, counts
    run.error_details = {'coverage': coverage} if partial else {}
    run.save()
    audit(run.actor, 'sync.partial' if partial else 'sync.succeeded', 'sync_run', run.pk, counts, run.pk, owner=owner)
    return counts
