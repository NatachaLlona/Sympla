from unittest.mock import patch,Mock
from django.test import SimpleTestCase
from django.core.cache import cache
from .routing import travel_times


class LocalRoutingTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.metadata={'status':'ready','sha256':'test-road-graph','bbox':[-44,-24,-42,-22],'region':'test-region'}
        self.points=[{'geography':{'code':'3304557'},'latitude':-22.9,'longitude':-43.2}]

    @patch('core.routing.metadata')
    @patch('core.routing.requests.Session')
    def test_local_car_times_and_cache(self,session,metadata):
        metadata.return_value=self.metadata
        response=Mock(status_code=200,content=b'valid')
        response.json.return_value={'code':'Ok','durations':[[120.0]]}
        session.return_value.__enter__.return_value.get.return_value=response
        values,meta=travel_times(self.points,(-22.91,-43.21))
        self.assertEqual(values['3304557'],2)
        self.assertEqual(meta['computed_locations'],1)
        travel_times(self.points,(-22.91,-43.21))
        self.assertEqual(session.return_value.__enter__.return_value.get.call_count,1)

    @patch('core.routing.metadata')
    @patch('core.routing.requests.Session')
    def test_outside_graph_is_unknown_without_network(self,session,metadata):
        metadata.return_value=self.metadata
        values,meta=travel_times(self.points,(-23.55,-46.63))
        self.assertIsNone(values['3304557'])
        self.assertEqual(meta['status'],'event_outside_coverage')
        session.assert_not_called()

    @patch('core.routing.metadata')
    @patch('core.routing.requests.Session')
    def test_engine_failure_never_becomes_zero_minutes(self,session,metadata):
        metadata.return_value=self.metadata
        session.return_value.__enter__.return_value.get.return_value=Mock(status_code=400)
        values,meta=travel_times(self.points,(-22.91,-43.21))
        self.assertIsNone(values['3304557'])
        self.assertEqual(meta['status'],'partial')
