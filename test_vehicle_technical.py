import copy
import unittest
from unittest.mock import patch, Mock

import cloud_app
import tirbazar
from config import Config
from vehicle_technical import source_record, kostka_candidates

VIN = 'WVWZZZ1KZ6W000001'
OTHER = 'WVWZZZ1KZ6W000002'


def state():
    return {'results': [{'vin': VIN, 'oid': None, 'status': 'NAVÍC V UNIQA'},
                        {'vin': OTHER, 'oid': None, 'pojistovna': 'ALLIANZ'}],
            'sql_technical': {'complete': True, 'fetched_at': '24.10.2026 21:50:00',
                              'vehicles': {VIN: {'oid': 20, 'data': {'TovarniZnacka': 'Ford', 'Palivo': 'Nafta'}}}}}


class TechnicalTests(unittest.TestCase):
    def setUp(self):
        config = patch.dict(cloud_app.app.config, SECRET_KEY='test-secret')
        config.start()
        self.addCleanup(config.stop)
        self.client = cloud_app.app.test_client()
        with self.client.session_transaction() as session:
            session['denni_pov_authenticated'] = True

    def get(self, data, vin=VIN):
        with patch.object(cloud_app, '_load_state', return_value=data):
            return self.client.get('/api/vehicle-technical/' + vin)

    def test_filtered_sql_vehicle_wins_even_with_insurance_only_result(self):
        data = state()
        before = copy.deepcopy(data)
        with patch.object(cloud_app, '_kostka_saved') as saved, patch.object(cloud_app, '_kostka_start') as start:
            response = self.get(data)
        self.assertEqual(response.json['source'], 'sql')
        self.assertEqual(response.json['oid'], 20)
        self.assertEqual(response.json['data']['Palivo'], 'Nafta')
        saved.assert_not_called()
        start.assert_not_called()
        self.assertEqual(data, before)

    def test_existing_kostka_cache_reused_for_insurance_only(self):
        with patch.object(cloud_app, '_kostka_saved', return_value=({'TovarniZnacka': 'Skoda'}, '2026-10-01')) as saved:
            response = self.get(state(), OTHER)
        self.assertEqual(response.json['source'], 'kostka')
        self.assertEqual(response.json['data']['TovarniZnacka'], 'Skoda')
        saved.assert_called_once_with(OTHER)

    def test_candidates_exclude_sql_and_duplicates(self):
        data = state()
        data['results'].extend([{'vin': OTHER.lower()}, {'vin': 'BAD'}])
        self.assertEqual(kostka_candidates(data), [OTHER])

    def test_legacy_snapshot_does_not_assume_missing_sql(self):
        data = {'results': [{'vin': OTHER}]}
        self.assertEqual(kostka_candidates(data), [])
        with patch.object(cloud_app, '_kostka_saved', return_value=None) as saved:
            response = self.get(data, OTHER)
        self.assertEqual(response.json['source'], 'unknown')
        saved.assert_called_once_with(OTHER)

    def test_legacy_cache_visible_without_fetch(self):
        with patch.object(cloud_app, '_kostka_saved', return_value=({'TovarniZnacka': 'Ford'}, '2026-10-01')), patch.object(cloud_app, '_kostka_start') as start:
            response = self.get({'results': [{'vin': OTHER}]}, OTHER)
        self.assertTrue(response.json['sql_pending'])
        self.assertEqual(response.json['data']['TovarniZnacka'], 'Ford')
        start.assert_not_called()

    def test_legacy_sql_basics_still_work(self):
        data = {'results': [{'vin': VIN, 'spz_tir': '1AA1111', 'znacka': 'Ford'}]}
        self.assertEqual(self.get(data).json['data']['TovarniZnacka'], 'Ford')

    def test_pending_starts_background_without_changing_insurance(self):
        data = state()
        with patch.object(cloud_app, '_DATABASE_URL', 'configured'), patch.object(cloud_app, '_kostka_keys', return_value=['secret']), patch.object(cloud_app, '_kostka_saved', return_value=None), patch.object(cloud_app, '_kostka_start') as start:
            response = self.get(data, OTHER)
        self.assertTrue(response.json['pending'])
        start.assert_called_once_with(data)

    def test_provider_empty_and_storage_unavailable(self):
        with patch.object(cloud_app, '_kostka_saved', return_value=({}, '2026-10-01')):
            self.assertIn('nemá', self.get(state(), OTHER).json['message'])
        with patch.object(cloud_app, '_kostka_saved', side_effect=RuntimeError):
            self.assertEqual(self.get(state(), OTHER).status_code, 503)

    def test_endpoint_auth_and_scope(self):
        self.assertEqual(self.get(state(), 'INVALID').status_code, 400)
        self.assertEqual(self.get({'results': []}).status_code, 404)
        self.assertEqual(cloud_app.app.test_client().get('/api/vehicle-technical/' + VIN).status_code, 401)

    def test_sql_metadata_stays_on_selected_oid(self):
        output = '\n'.join([
            '__TOTAL__|2',
            f'__ROW__|10|{VIN}|1AA1111|Vykoupené|2025-01-01|||CZ|',
            f'__ROW__|20|{VIN}|2AA2222|Vykoupené|2026-01-01|||CZ|',
            '__VEHICLE_META__|10|Ford|Transit', '__VEHICLE_META__|20|Skoda|Octavia',
            '__TECHNICAL__|10|MotorMaxVykon|100', '__TECHNICAL__|20|MotorMaxVykon|150',
        ])
        with patch.object(tirbazar.Path, 'exists', return_value=True), patch.object(tirbazar.Path, 'write_text'), patch.object(tirbazar, 'get_password', return_value='test'), patch.object(tirbazar.subprocess, 'run', return_value=Mock(returncode=0, stdout=output, stderr='')):
            vehicles, duplicates = tirbazar.load_tirbazar_vehicles(Config('', 1433, '', '', ''))
        self.assertEqual(vehicles[0].oid, 20)
        self.assertEqual(vehicles[0].technical['MotorMaxVykon'], '150')
        self.assertEqual(duplicates[0][1].technical['MotorMaxVykon'], '100')
        tirbazar.validate_read_only(tirbazar.build_sql())


class StandaloneCardTests(unittest.TestCase):
    def test_sql_card_never_requests_kostka(self):
        import vehicle_card
        with patch.dict('os.environ', {'ONLINE_MODE': '1'}), patch.object(cloud_app, '_load_state', return_value=state()), patch.object(vehicle_card, '_kostka_fetch') as fetch:
            raw, source, oid = vehicle_card._card_technical_data(VIN)
        self.assertEqual((source, oid), ('SQL Vans Centre', 20))
        self.assertEqual(raw['Palivo'], 'Nafta')
        fetch.assert_not_called()

    def test_standalone_reuses_existing_kostka_data(self):
        import vehicle_card
        with patch.dict('os.environ', {'ONLINE_MODE': '1'}), patch.object(cloud_app, '_load_state', return_value=state()), patch.object(cloud_app, '_kostka_saved', return_value=({'TovarniZnacka': 'Skoda'}, 'date')), patch.object(vehicle_card, '_kostka_fetch') as fetch:
            raw, source, oid = vehicle_card._card_technical_data(OTHER)
        self.assertEqual(source, 'Datová kostka')
        self.assertEqual(raw['TovarniZnacka'], 'Skoda')
        fetch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
