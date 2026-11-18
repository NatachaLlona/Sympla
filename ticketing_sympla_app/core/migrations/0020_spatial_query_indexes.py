from django.db import migrations


def install(apps, schema_editor):
    schema_editor.execute('CREATE INDEX IF NOT EXISTS map_lat_lon_lookup ON core_geographymapreference(latitude, longitude)')
    schema_editor.execute('CREATE INDEX IF NOT EXISTS stat_owned_scope_lookup ON core_statistic(integration_id, period, geography_id, category_id)')
    if schema_editor.connection.vendor == 'postgresql':
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_available_extensions WHERE name='postgis'")
            available = cursor.fetchone()
        if available:
            schema_editor.execute('CREATE EXTENSION IF NOT EXISTS postgis')
            schema_editor.execute('CREATE INDEX IF NOT EXISTS map_seat_geography_gist ON core_geographymapreference USING gist ((ST_SetSRID(ST_MakePoint(longitude::double precision,latitude::double precision),4326)::geography)) WHERE latitude IS NOT NULL AND longitude IS NOT NULL')


class Migration(migrations.Migration):
    dependencies = [('core', '0019_protect_analysis_history')]
    operations = [migrations.RunPython(install)]
