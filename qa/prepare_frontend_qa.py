"""Prepare the named disposable frontend QA stack using official public IBGE data."""
import importlib.util
import json
import subprocess
from pathlib import Path
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('frontend_qa_launcher', ROOT/'start.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def main():
    path = ROOT/'.qa-local/config.jsonc'
    config = json.loads(path.read_text())
    assert config['docker']['project_name'] == 'sympla-startup-qa'
    assert config['database']['name'] == 'SimplaQA' and config['api']['port'] == 18010
    config['frontend'] = {'port': 18011}
    config['audience_map'] = {'port': 18012}
    config['auth']['token_ttl_seconds'] = 3600
    path.write_text(json.dumps(config), encoding='utf-8')
    assert launcher.main(['--config', str(path), '--state-dir', str(ROOT/'.qa-local/state')]) == 0
    def request(path, payload=None, token=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer '+token
        with urlopen(Request('http://127.0.0.1:18011'+path, data=json.dumps(payload).encode() if payload is not None else None, headers=headers), timeout=60) as response:
            return json.load(response)
    token = request('/api/v1/token/', {'grant_type': 'client_credentials', 'client_id': 'qa-client', 'client_secret': 'QaRotatedPass1!'})['access_token']
    existing = request('/api/v1/integrations/', token=token)['results']
    integration = next((row for row in existing if row['name'] == 'Frontend QA - São Paulo/SP'), None)
    if not integration:
        integration = request('/api/v1/integrations/', {'name': 'Frontend QA - São Paulo/SP', 'provider': 'ibge',
            'configuration': {'state_codes': ['35'], 'municipality_codes': ['3550308'], 'levels': ['state', 'city', 'neighborhood']}}, token)
    if request('/api/v1/demographics/?integration_id='+integration['id']+'&indicator=age_population', token=token)['count'] == 0:
        run = request('/api/v1/sync/', {'integration_id': integration['id']}, token)
        print('Preparing public IBGE observations for the isolated frontend QA stack.', flush=True)
        deadline = time.monotonic()+300
        while time.monotonic() < deadline:
            status = request(run['status_url'], token=token)
            if status['status'] not in ('queued', 'running'):
                assert status['status'] in ('success', 'partial'), status['error_code']
                break
            time.sleep(2)
        else:
            raise AssertionError('The QA IBGE import did not complete.')
    options = request('/api/v1/demographics/explorer-options/', token=token)
    assert options['integrations']
    result = request('/api/v1/demographics/search/?integration_id='+integration['id']+'&age_min=4&age_max=8&level=district', token=token)
    assert result['count'] == 96
    print('PASS: disposable frontend QA stack has official age data for 96 São Paulo districts.', flush=True)
    subprocess.run(['docker', 'exec', 'sympla-startup-qa-api-1', 'python', 'manage.py',
                    'configure_ibge_capitals', '--client-id', 'qa-client'], check=True)
    national = next(row for row in request('/api/v1/integrations/', token=token)['results']
                    if row['configuration'].get('geographic_preset') == 'capital_metropolitan_areas_2025')
    deadline = time.monotonic()+300
    while time.monotonic() < deadline:
        runs = request('/api/v1/sync-runs/?integration_id='+national['id'], token=token)
        if not any(row['status'] in ('queued', 'running') for row in runs['results']):
            break
        time.sleep(2)
    result = request('/api/v1/demographics/search/?integration_id='+national['id']+'&age_min=4&age_max=8&level=city', token=token)
    assert result['count'] == 430
    print('PASS: national frontend QA scope has 430 municipalities.', flush=True)
    fixture = "from core.models import ApiUser,Integration,Event,EventAddress; a=ApiUser.objects.get(client_id='qa-client'); i=Integration.objects.filter(owner=a,provider='sympla').first(); e,_=Event.objects.get_or_create(owner=a,integration=i,external_id='map-qa-event',defaults={'name':'QA event - Sao Paulo'}); EventAddress.objects.update_or_create(event=e,defaults={'lat':'-23.55','lon':'-46.63','city':'Sao Paulo','state':'SP'}); print('Isolated map event fixture ready.')"
    subprocess.run(['docker', 'exec', 'sympla-startup-qa-api-1', 'python', 'manage.py', 'shell', '-c', fixture], check=True)


if __name__ == '__main__':
    main()
