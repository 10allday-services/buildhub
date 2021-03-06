# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, you can obtain one at http://mozilla.org/MPL/2.0/.

import asyncio
import datetime
import json
from unittest import mock

import pytest
import aiohttp
import asynctest
from aioresponses import aioresponses

from buildhub import inventory_to_records, utils
from buildhub.utils import ARCHIVE_URL  # shortcut


class LongResponse:
    def raise_for_status(self):
        pass

    def __init__(self, *args, **kwargs):
        self.status = kwargs.get('status', 200)

    async def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self, *args):
        return self

    async def __aexit__(self, *args):
        pass

    async def json(self):
        return await asyncio.sleep(10000)


class FetchJsonTest(asynctest.TestCase):
    url = 'http://test.example.com'
    data = {'foo': 'bar'}

    async def setUp(self):
        self.session = aiohttp.ClientSession(loop=self.loop)
        self.addCleanup(self.session.close)

    async def test_returns_json_response(self):
        with aioresponses() as m:
            m.get(self.url, payload=self.data)
            received = await inventory_to_records.fetch_json(
                self.session,
                self.url
            )
        assert received == self.data

    async def test_supports_octet_stream(self):
        with aioresponses() as m:
            headers = {'Content-Type': 'application/octet-stream'}
            m.get(self.url, body=json.dumps(self.data), headers=headers)
            received = await inventory_to_records.fetch_json(
                self.session,
                self.url
            )
        assert received == self.data

    async def test_raises_timeout_response(self):
        with asynctest.patch.object(self.session, 'get', LongResponse):
            with self.assertRaises(asyncio.TimeoutError):
                await inventory_to_records.fetch_json(
                    self.session,
                    self.url,
                    0.1
                )

    async def test_retries_when_status_is_not_found(self):
        with aioresponses() as m:
            headers = {'Content-Type': 'text/html'}
            m.get(
                self.url,
                body="<html><body></body></html>",
                status=404,
                headers=headers
            )
            m.get(self.url, payload=self.data)
            received = await inventory_to_records.fetch_json(
                self.session,
                self.url,
                retry_on_notfound=True
            )
        assert received == self.data

    async def test_fails_when_status_is_never_found(self):
        with aioresponses() as m:
            headers = {'Content-Type': 'text/html'}
            # Since it retries 3 times, sends 4 bad responses.
            m.get(
                self.url,
                body="<html><body></body></html>",
                status=404,
                headers=headers
            )
            m.get(
                self.url,
                body="<html><body></body></html>",
                status=404,
                headers=headers
            )
            m.get(
                self.url,
                body="<html><body></body></html>",
                status=404,
                headers=headers
            )
            m.get(
                self.url,
                body="<html><body></body></html>",
                status=404,
                headers=headers
            )
            with self.assertRaises(inventory_to_records.JSONFileNotFound):
                await inventory_to_records.fetch_json(self.session, self.url)

    async def test_fails_when_status_is_never_found_with_retry(self):
        with aioresponses() as m:
            headers = {'Content-Type': 'text/html'}
            # Since it retries 3 times, sends 4 bad responses.
            m.get(
                self.url,
                body="<html><body></body></html>",
                status=404,
                headers=headers
            )
            m.get(
                self.url,
                body="<html><body></body></html>",
                status=404,
                headers=headers
            )
            m.get(
                self.url,
                body="<html><body></body></html>",
                status=404,
                headers=headers
            )
            m.get(
                self.url,
                body="<html><body></body></html>",
                status=404,
                headers=headers
            )
            # If you force it to retry on 404s and never succeeds it
            # will eventually raise a ClientError
            with self.assertRaises(aiohttp.ClientError):
                await inventory_to_records.fetch_json(
                    self.session,
                    self.url,
                    retry_on_notfound=True,
                )

    async def test_fails_when_status_is_never_ok(self):
        with aioresponses() as m:
            headers = {'Content-Type': 'text/html'}
            # Since it retries 3 times, sends 4 bad responses.
            m.get(
                self.url,
                body="<html><body></body></html>",
                status=503,
                headers=headers
            )
            m.get(
                self.url,
                body="<html><body></body></html>",
                status=503,
                headers=headers
            )
            m.get(
                self.url,
                body="<html><body></body></html>",
                status=503,
                headers=headers
            )
            m.get(
                self.url,
                body="<html><body></body></html>",
                status=503,
                headers=headers
            )
            with self.assertRaises(aiohttp.ClientError):
                await inventory_to_records.fetch_json(self.session, self.url)


class FetchListingTest(asynctest.TestCase):
    url = 'http://test.example.com'

    async def setUp(self):
        self.session = aiohttp.ClientSession(loop=self.loop)
        self.addCleanup(self.session.close)

    async def test_returns_tuple_with_directories_and_files(self):
        with aioresponses() as m:
            m.get(self.url, payload={
                'prefixes': ['a/', 'b/'],
                'files': [{'name': 'foo.txt'}]
            })
            received = await inventory_to_records.fetch_listing(
                self.session,
                self.url
            )
            assert received == (['a/', 'b/'], [{'name': 'foo.txt'}])

    async def test_raises_valueerror_if_bad_json(self):
        with aioresponses() as m:
            m.get(self.url, payload={
                'prfixes': ['a/', 'b/'],
            })
            with self.assertRaises(ValueError):
                await inventory_to_records.fetch_listing(
                    self.session,
                    self.url
                )

    async def test_raises_valueerror_if_html(self):
        with aioresponses() as m:
            m.get(self.url, body='<html></html>')
            with self.assertRaises(ValueError):
                await inventory_to_records.fetch_listing(
                    self.session,
                    self.url
                )

    async def test_jsonnotfound_exception(self):
        with aioresponses() as m:
            m.get(self.url, status=404)
            with self.assertRaises(inventory_to_records.JSONFileNotFound):
                await inventory_to_records.fetch_listing(
                    self.session,
                    self.url,
                )

    async def test_retries_in_case_of_404_response(self):
        with aioresponses() as m:
            m.get(self.url, status=404)
            m.get(self.url, payload={
                'prefixes': ['a/', 'b/'],
                'files': [{'name': 'foo.txt'}]
            })
            received = await inventory_to_records.fetch_listing(
                self.session,
                self.url,
                retry_on_notfound=True
            )
            assert received == (['a/', 'b/'], [{'name': 'foo.txt'}])


class FetchNightlyMetadata(asynctest.TestCase):
    async def setUp(self):
        self.session = aiohttp.ClientSession(loop=self.loop)
        self.addCleanup(self.session.close)

    def tearDown(self):
        inventory_to_records._nightly_metadata.clear()

    async def test_fetch_nightly_metadata(self):
        record = {
            'id': 'a',
            'download': {'url': 'http://server.org/firefox.fr.win32.exe'}
        }

        with aioresponses() as m:
            m.get('http://server.org/firefox.en-US.win32.json', payload={
                'buildid': '20170512'
            })
            received = await inventory_to_records.fetch_nightly_metadata(
                self.session,
                record
            )
        assert received == {'buildid': '20170512'}

    async def test_does_not_hit_server_if_already_known(self):
        record = {
            'id': 'a',
            'download': {'url': 'http://server.org/firefox.fr.win32.exe'}
        }

        with aioresponses() as m:
            m.get('http://server.org/firefox.en-US.win32.json', payload={
                'buildid': '20170512'
            })
            await inventory_to_records.fetch_nightly_metadata(
                self.session,
                record
            )

        record['download']['url'] = record['download']['url'].replace(
            '.fr.', '.it.'
        )
        # Now cached, no need to mock HTTP responses.
        received = await inventory_to_records.fetch_nightly_metadata(
            self.session,
            record
        )
        assert received == {'buildid': '20170512'}

    async def test_returns_none_if_not_available(self):
        record = {
            'id': 'a',
            'download': {'url': 'http://archive.org/firefox.fr.win32.exe'}
        }
        with aioresponses() as m:
            m.get(
                'http://archive.org/firefox.en-US.win32.json',
                exception=aiohttp.ClientError
            )
            received = await inventory_to_records.fetch_nightly_metadata(
                self.session,
                record
            )
        assert received is None

    async def test_fetch_nightly_metadata_from_installer_url(self):
        record = {'id': 'a', 'download': {
            'url': 'http://server.org/firefox.fr.win64.installer.exe'}}

        with aioresponses() as m:
            m.get('http://server.org/firefox.en-US.win64.json', payload={
                'buildid': '20170512'
            })
            received = await inventory_to_records.fetch_nightly_metadata(
                self.session,
                record
            )
        assert received == {'buildid': '20170512'}

    async def test_fetch_old_nightly_metadata_from_txt(self):
        record = {
            'id': 'a',
            'download': {
                'url': (
                    'http://server.org/firefox-6.0a1.en-US.linux-x86_64'
                    '.tar.bz2'
                )
            }
        }
        with aioresponses() as m:
            m.get(
                'http://server.org/firefox-6.0a1.en-US.linux-x86_64.json',
                status=404,
            )
            m.get(
                'http://server.org/firefox-6.0a1.en-US.linux-x86_64.txt',
                body=(
                    '20110505030608\n'
                    'http://hg.mozilla.org/mozilla-central/rev/31879b88cc82'
                ),
                headers={'Content-type': 'text/plain'}
            )
            received = await inventory_to_records.fetch_nightly_metadata(
                self.session,
                record
            )
        assert received == {
            'buildid': '20110505030608',
            'moz_source_repo': 'http://hg.mozilla.org/mozilla-central',
            'moz_source_stamp': '31879b88cc82',
        }

    async def test_fetch_very_old_nightly_metadata_from_txt(self):
        record = {
            'id': 'a',
            'download': {
                'url': (
                    'http://server.org/firefox-6.0a1.en-US.linux-x86_64'
                    '.tar.bz2'
                ),
            }
        }
        with aioresponses() as m:
            m.get(
                'http://server.org/firefox-6.0a1.en-US.linux-x86_64.json',
                status=404,
            )
            m.get('http://server.org/firefox-6.0a1.en-US.linux-x86_64.txt',
                  body=('20100704054020 55f39d8d866c'),
                  headers={'Content-type': 'text/plain'})
            received = await inventory_to_records.fetch_nightly_metadata(
                self.session,
                record
            )
        assert received == {
            'buildid': '20100704054020',
            'moz_source_repo': 'http://hg.mozilla.org/mozilla-central',
            'moz_source_stamp': '55f39d8d866c'
        }


class FetchRCMetadata(asynctest.TestCase):
    async def setUp(self):
        self.session = aiohttp.ClientSession(loop=self.loop)
        self.addCleanup(self.session.close)

    def tearDown(self):
        inventory_to_records._rc_metadata.clear()

    async def test_fetch_rc_metadata(self):
        with aioresponses() as m:
            m.get('http://server.org/54.0-candidates/build3/'
                  'win64/en-US/firefox-54.0.json',
                  payload={'buildid': '20170512'})
            result = await inventory_to_records.fetch_release_candidate_metadata(  # noqa
                self.session, {
                    'download': {
                        'url': 'http://server.org/54.0-candidates/build3/'
                               'win64/en-US/Firefox%20Setup%2054.0.exe'
                    },
                    'target': {'version': '54.0rc3'},
                    'source': {'product': 'firefox'}
                })
            assert result == {'buildid': '20170512', 'buildnumber': 3}

    async def test_fetch_rc_metadata_mac(self):
        with aioresponses() as m:
            m.get('http://server.org/pub/firefox/candidates/54.0-candidates/'
                  'build2/mac/en-US/firefox-54.0.json',
                  payload={'buildid': '20170512'})
            result = await inventory_to_records.fetch_release_candidate_metadata(  # noqa
                self.session, {
                    'download': {
                        'url': 'http://server.org/pub/firefox/candidates/54.0-'
                               'candidates/build2/mac/de/Firefox%2054.0.dmg'
                    },
                    'target': {'version': '54.0rc2'},
                    'source': {'product': 'firefox'}
                })
            assert result == {'buildid': '20170512', 'buildnumber': 2}

    async def test_fetch_rc_metadata_win(self):
        with aioresponses() as m:
            m.get('http://server.org/pub/firefox/candidates/54.0-candidates/'
                  'build2/win64/en-US/firefox-54.0.json',
                  payload={'buildid': '20170512'})
            result = await inventory_to_records.fetch_release_candidate_metadata(  # noqa
                self.session, {
                    'download': {
                        'url': (
                            'http://server.org/pub/firefox/candidates/'
                            '54.0-candidates/build2/win64/fr/'
                            'Firefox%20Setup%2054.0.exe'
                        )
                    },
                    'target': {'version': '54.0rc2'},
                    'source': {'product': 'firefox'}
                })
            assert result == {'buildid': '20170512', 'buildnumber': 2}

    async def test_fetch_rc_metadata_fennec(self):
        with aioresponses() as m:
            m.get(
                (
                    'http://server.org/pub/mobile/candidates/49.0-candidates/'
                    'build2/android-api-15/en-US/fennec-49.0.en-US'
                    '.android-arm.json'
                ),
                payload={'buildid': '20170512'}
            )
            result = await inventory_to_records.fetch_release_candidate_metadata(  # noqa
                self.session, {
                    'download': {
                        'url': (
                            'http://server.org/pub/mobile/candidates/'
                            '49.0-candidates/build2/android-api-15/en-US/'
                            'fennec-49.0.en-US.android-arm.apk'
                        )
                    },
                    'target': {'version': '49.0rc2'},
                    'source': {'product': 'fennec'}
                })
            assert result == {'buildid': '20170512', 'buildnumber': 2}

    async def test_fetch_rc_metadata_beta(self):
        with aioresponses() as m:
            m.get(
                (
                    'http://server.org/pub/devedition/candidates/'
                    '55.0b1-candidates/build5/win64/en-US/firefox-55.0b1.json'
                ),
                payload={'buildid': '20170512'})
            result = await inventory_to_records.fetch_release_candidate_metadata(  # noqa
                self.session, {
                    'download': {
                        'url': (
                            'http://server.org/pub/devedition/candidates/'
                            '55.0b1-candidates/build5/win64/pt-BR/'
                            'Firefox%20Setup%2055.0b1.exe'
                        ),
                    },
                    'target': {'version': '55.0b1'},
                    'source': {'product': 'devedition'}
                })
            assert result == {'buildid': '20170512', 'buildnumber': 5}

    async def test_does_not_hit_server_if_already_known(self):
        url = (
            'http://server.org/54.0-candidates/build3/win64/en-US/'
            'firefox.en-US.win32.zip'
        )
        metadata = {'a': 1, 'b': 2}
        inventory_to_records._rc_metadata[url] = metadata
        result = await inventory_to_records.fetch_release_candidate_metadata(
            self.session,
            {
                'download': {'url': url}
            }
        )
        assert result == metadata


class FetchReleaseMetadata(asynctest.TestCase):
    async def setUp(self):
        self.session = aiohttp.ClientSession(loop=self.loop)
        self.addCleanup(self.session.close)

        inventory_to_records._candidates_build_folder['firefox'] = {
            '54.0': 'build3/',
            '57.0b4': 'build1/',
            '47.0.1': 'build1/',
        }
        self.record = {
            'source': {'product': 'firefox'},
            'target': {
                'version': '54.0',
                'platform': 'win64',
                'locale': 'fr-FR',
            }
        }

    def tearDown(self):
        inventory_to_records._candidates_build_folder.clear()
        inventory_to_records._release_metadata.clear()

    async def test_fetch_release_metadata_unknown_version(self):
        result = await inventory_to_records.fetch_release_metadata(
            self.session,
            {
                'source': {'product': 'firefox'},
                'target': {'version': '1.0', 'platform': 'p'}
            }
        )
        assert result is None

    async def test_fetch_release_metadata_update_release(self):
        result = await inventory_to_records.fetch_release_metadata(
            self.session,
            {
                'source': {'product': 'firefox'},
                'target': {'version': '1.0', 'platform': 'p'}
            }
        )
        assert result is None

    async def test_fetch_release_metadata_for_partial_update(self):
        record = {
            'source': {'product': 'firefox'},
            'target': {'version': '47.0.1', 'platform': 'win64'}
        }
        archive_url = utils.ARCHIVE_URL + 'pub/firefox/candidates/'
        with aioresponses() as m:
            build_folder = archive_url + '47.0.1-candidates/build1/'
            m.get(build_folder, payload={
                'prefixes': [
                    'update/'
                ],
                'files': [
                    {'name': 'KEY'},
                    {'name': 'SHA512SUMS'},
                ]
            })
            received = await inventory_to_records.fetch_release_metadata(
                self.session,
                record
            )
            assert received is None
        # Now cached, no need to mock HTTP responses.
        received = await inventory_to_records.fetch_release_metadata(
            self.session,
            record
        )
        assert received is None

    async def test_fetch_release_metadata_server_fails(self):
        archive_url = utils.ARCHIVE_URL + 'pub/firefox/candidates/'
        with aioresponses() as m:
            candidate_folder = (
                archive_url + '54.0-candidates/build3/win64/en-US/'
            )
            m.get(candidate_folder, payload={
                'prefixes': [], 'files': [
                    {'name': 'firefox-54.0.json'}
                ]
            })
            headers = {'Content-Type': 'application/xml'}
            body = '<pim><pooom/></pim>'
            m.get(
                candidate_folder + 'firefox-54.0.json',
                body=body,
                headers=headers
            )

            with self.assertRaises(ValueError):
                await inventory_to_records.fetch_release_metadata(
                    self.session,
                    self.record
                )

    async def test_fetch_release_metadata_mac(self):
        record = {
            'source': {'product': 'firefox'},
            'target': {
                'version': '57.0b4',
                'platform': 'macosx',
                'locale': 'fr-FR',
            }
        }
        archive_url = utils.ARCHIVE_URL + 'pub/firefox/candidates/'
        with aioresponses() as m:
            candidate_folder = (
                archive_url + '57.0b4-candidates/build1/mac/en-US/'
            )
            m.get(
                candidate_folder,
                payload={
                    'prefixes': [], 'files': [
                        {'name': 'firefox-57.0b4.json'}
                    ]
                }
            )
            m.get(
                candidate_folder + 'firefox-57.0b4.json',
                payload={'buildid': '20170928180207'}
            )
            received = await inventory_to_records.fetch_release_metadata(
                self.session,
                record
            )
            assert received == {
                'buildid': '20170928180207',
                'buildnumber': 1,
            }
        # Now cached, no need to mock HTTP responses.
        received = await inventory_to_records.fetch_release_metadata(
            self.session,
            record
        )
        assert received == {
            'buildid': '20170928180207',
            'buildnumber': 1,
        }

    async def test_fetch_release_metadata_failing(self):
        archive_url = utils.ARCHIVE_URL + 'pub/firefox/candidates/'
        with aioresponses() as m:
            candidate_folder = (
                archive_url + '54.0-candidates/build3/win64/en-US/'
            )
            m.get(candidate_folder, payload={
                'prefixes': [], 'files': [
                    {'name': 'only-a-random-file.json'}
                ]
            })
            with self.assertRaises(ValueError):
                await inventory_to_records.fetch_release_metadata(
                    self.session,
                    self.record
                )
        # If we retry, no request is made.
        assert await inventory_to_records.fetch_release_metadata(
            self.session,
            self.record
        ) is None

    async def test_fetch_metadata_from_eme_url(self):
        # /pub/firefox/candidates/54.0-candidates/build3/mac-EME-free/dsb/Firefox%2054.0.dmg
        record = {
            'source': {'product': 'firefox'},
            'target': {
                'version': '54.0',
                'platform': 'mac-eme-free',
                'locale': 'dsb',
            }
        }
        with aioresponses() as m:
            archive_url = utils.ARCHIVE_URL + 'pub/firefox/candidates/'
            candidate_folder = (
                archive_url + '54.0-candidates/build3/mac/en-US/'
            )
            m.get(
                candidate_folder,
                payload={
                    'prefixes': [], 'files': [
                        {'name': 'firefox-54.0.json'}
                    ]
                }
            )
            m.get(
                candidate_folder + 'firefox-54.0.json',
                payload={'buildid': '20170512'}
            )
            received = await inventory_to_records.fetch_release_metadata(
                self.session,
                record
            )
            assert received == {
                'buildid': '20170512',
                'buildnumber': 3,
            }

    async def test_fetch_metadata_from_linux_eme_url(self):
        record = {
            'source': {'product': 'firefox'},
            'target': {
                'version': '54.0',
                'platform': 'linux-x86_64-eme-free',
                'locale': 'fr-FR',
            }
        }
        with aioresponses() as m:
            archive_url = utils.ARCHIVE_URL + 'pub/firefox/candidates/'
            candidate_folder = (
                archive_url + '54.0-candidates/build3/linux-x86_64/en-US/'
            )
            m.get(
                candidate_folder,
                payload={
                    'prefixes': [], 'files': [
                        {'name': 'firefox-54.0.json'}
                    ]
                }
            )
            m.get(
                candidate_folder + 'firefox-54.0.json',
                payload={'buildid': '20170512'}
            )
            received = await inventory_to_records.fetch_release_metadata(
                self.session,
                record
            )
            assert received == {
                'buildid': '20170512',
                'buildnumber': 3,
            }

    async def test_fetch_metadata_from_sha1(self):
        # /pub/firefox/releases/45.3.0esr/win64-sha1/fy-NL/Firefox%20Setup%2045.3.0esr.exe
        inventory_to_records._candidates_build_folder['firefox'] = {
            '45.3.0esr': 'build3/'
        }
        record = {
            'source': {'product': 'firefox'},
            'target': {
                'version': '45.3.0esr',
                'platform': 'win64-sha1',
                'locale': 'fy-NL',
            }
        }
        with aioresponses() as m:
            archive_url = utils.ARCHIVE_URL + 'pub/firefox/candidates/'
            candidate_folder = (
                archive_url + '45.3.0esr-candidates/build3/win64/en-US/'
            )
            m.get(
                candidate_folder,
                payload={
                    'prefixes': [], 'files': [
                        {'name': 'firefox-45.3.0esr.json'}
                    ]
                }
            )
            m.get(
                candidate_folder + 'firefox-45.3.0esr.json',
                payload={'buildid': '20170512'}
            )
            received = await inventory_to_records.fetch_release_metadata(
                self.session,
                record
            )
            assert received == {'buildid': '20170512', 'buildnumber': 3}


class ScanCandidates(asynctest.TestCase):
    async def setUp(self):
        self.session = aiohttp.ClientSession(loop=self.loop)
        self.addCleanup(self.session.close)

    def tearDown(self):
        inventory_to_records._candidates_build_folder.clear()

    async def test_scan_candidates_does_nothing_if_already_done(self):
        inventory_to_records._candidates_build_folder['firefox'] = {}
        await inventory_to_records.scan_candidates(self.session, 'firefox')

    async def test_scan_candidates(self):
        with aioresponses() as m:
            candidates_listing = utils.ARCHIVE_URL + 'pub/firefox/candidates/'
            m.get(candidates_listing, payload={
                'prefixes': [
                    '54.0-candidates/',
                    '52.0.2esr-candidates/',
                    'archived/'
                ], 'files': []
            })
            m.get(candidates_listing + '52.0.2esr-candidates/', payload={
                'prefixes': [
                    'build1/',
                    'build2/',
                    'build3/',
                ], 'files': []
            })
            m.get(candidates_listing + '54.0-candidates/', payload={
                'prefixes': [
                    'build11/',
                    'build9/',
                    'build3/',
                    'pop/',
                ], 'files': []
            })
            await inventory_to_records.scan_candidates(self.session, 'firefox')

            assert inventory_to_records._candidates_build_folder == {
                'firefox': {
                    '54.0': 'build11/',
                    '52.0.2esr': 'build3/',
                }
            }


class CSVToRecords(asynctest.TestCase):

    remote_content = {
        'pub/firefox/candidates/': {
            'prefixes': [
                '51.0-candidates/',
                'archived/'
            ], 'files': []
        },
        'pub/firefox/candidates/51.0-candidates/': {
            'prefixes': [
                'build1/',
                'build2/',
            ], 'files': []
        },
        'pub/firefox/candidates/51.0-candidates/build2/win64/en-US/': {
            'prefixes': [], 'files': [
                {'name': 'firefox-51.0.json'}
            ]
        },
        (
            'pub/firefox/candidates/51.0-candidates/build2/win64/en-US/'
            'firefox-51.0.json'
        ): {
            'as': 'ml64.exe',
            'buildid': '20170118123726',
            'cc': (
                'c:/builds/moz2_slave/m-rel-w64-00000000000000000000/build/',
                'src/vs2015u3/VC/bin/amd64/cl.EXE'
            ),
            'cxx': (
                'c:/builds/moz2_slave/m-rel-w64-00000000000000000000/build/',
                'src/vs2015u3/VC/bin/amd64/cl.EXE'
            ),
            'host_alias': 'x86_64-pc-mingw32',
            'host_cpu': 'x86_64',
            'host_os': 'mingw32',
            'host_vendor': 'pc',
            'ld': (
                'c:/builds/moz2_slave/m-rel-w64-00000000000000000000/build/',
                'src/vs2015u3/VC/bin/amd64/link.exe'
            ),
            'moz_app_id': '{ec8030f7-c20a-464f-9b0e-13a3a9e97384}',
            'moz_app_maxversion': '51.*',
            'moz_app_name': 'firefox',
            'moz_app_vendor': 'Mozilla',
            'moz_app_version': '51.0',
            'moz_pkg_platform': 'win64',
            'moz_source_repo': (
                'MOZ_SOURCE_REPO=https://hg.mozilla.org/releases'
                '/mozilla-release'
            ),
            'moz_source_stamp': 'ea82b5e20cbbd103f8fa65f0df0386ee4135cc47',
            'moz_update_channel': 'release',
            'target_alias': 'x86_64-pc-mingw32',
            'target_cpu': 'x86_64',
            'target_os': 'mingw32',
            'target_vendor': 'pc'
        }

    }

    @pytest.fixture(autouse=True)
    def init_cache_folder(self, tmpdir):
        # Use str() on these LocalPath instances to turn them into plain
        # strings since to_kinto.fetch_existing() expects it to be a string.
        self.cache_folder = str(tmpdir)

    async def setUp(self):
        mocked = aioresponses()
        mocked.start()
        for url, payload in self.remote_content.items():
            mocked.get(utils.ARCHIVE_URL + url, payload=payload)
        # This will be attempted every time since the metadata cache_folder
        # is always reset by the pytest fixture.
        mocked.get(
            utils.ARCHIVE_URL + 'pub/firefox/nightly/2017/06/2017-06-16-03-02'
            '-07-mozilla-central/firefox-56.0a1.en-US.win32.json',
            status=404
        )
        self.addCleanup(mocked.stop)

        # inventory_to_records._candidates_build_folder.clear()

        async def async_gen():
            _csv_input = (
                'net-mozaws-delivery-firefox,pub/firefox/releases/51.0/win64/'
                'fy-NL/Firefox Setup 51.0.exe,67842,2017-06-11T12:20:10.2Z,'
                'f1aa742ef0973db098947bd6d875f193\n'
                'net-mozaws-delivery-firefox,pub/firefox/nightly/2017/06/'
                '2017-06-16-03-02-07-mozilla-central-l10n/firefox-56.0a1'
                '.ach.win32.installer.exe,45678,2017-06-16T03:02:07.0Z,'
                'f1aa742ef0973db098947bd6d875f193\n'
                'net-mozaws-delivery-firefox,pub/firefox/nightly/2017/06/'
                '2017-06-16-03-02-07-mozilla-central-l10n/firefox-56.0a1'
                '.ach.win32.zip,45678,2017-06-16T03:02:07.0Z,'
                'f1aa742ef0973db098947bd6d875f193\n'
            )
            for line in utils.chunked(_csv_input, 32):
                yield bytes(line, 'utf-8')

        self.stdin = async_gen()

    def tearDown(self):
        inventory_to_records._candidates_build_folder.clear()

    async def test_csv_to_records(self):

        output = inventory_to_records.csv_to_records(
            self.loop,
            self.stdin,
            cache_folder=self.cache_folder,
        )
        records = []
        async for r in output:
            records.append(r)

        assert len(records) == 1
        print(records[0]['data']['download'])
        assert records == [{
            'data': {
                'id': 'firefox_51-0_win64_fy-nl',
                'build': {
                    'id': '20170118123726',
                    'date': '2017-01-18T12:37:26Z',
                    'number': 2,
                    'as': 'ml64.exe',
                    'cc': [
                        (
                            'c:/builds/moz2_slave/m-rel-w64-'
                            '00000000000000000000/build/'
                        ),
                        'src/vs2015u3/VC/bin/amd64/cl.EXE'
                    ],
                    'cxx': [
                        (
                            'c:/builds/moz2_slave/m-rel-w64-'
                            '00000000000000000000/build/'
                        ),
                        'src/vs2015u3/VC/bin/amd64/cl.EXE'
                    ],
                    'date': '2017-01-18T12:37:26Z',
                    'host': 'x86_64-pc-mingw32',
                    'ld': [
                        (
                            'c:/builds/moz2_slave/m-rel-w64-'
                            '00000000000000000000/build/'
                        ),
                        'src/vs2015u3/VC/bin/amd64/link.exe'
                    ],
                    'target': 'x86_64-pc-mingw32'
                },
                'download': {
                    'date': '2017-06-11T12:20:10Z',
                    'mimetype': 'application/msdos-windows',
                    'size': 67842,
                    'url': (
                        f'{ARCHIVE_URL}pub/firefox/releases/'
                        '51.0/win64/fy-NL/Firefox Setup 51.0.exe'
                    )
                },
                'source': {
                    'product': 'firefox',
                    'repository': (
                        'https://hg.mozilla.org/releases/mozilla-release'
                    ),
                    'revision': 'ea82b5e20cbbd103f8fa65f0df0386ee4135cc47',
                    'tree': 'releases/mozilla-release'
                },
                'target': {
                    'channel': 'release',
                    'locale': 'fy-NL',
                    'platform': 'win64',
                    'os': 'win',
                    'version': '51.0'
                }
            }
        }]

    async def test_csv_to_records_ancient_entries_skipped(self):

        today = datetime.datetime.utcnow()
        recently = today - datetime.timedelta(hours=1)
        # Make it timezone aware (to UTC)
        recently = recently.replace(tzinfo=datetime.timezone.utc)

        output = inventory_to_records.csv_to_records(
            self.loop,
            self.stdin,
            min_last_modified=recently,
            cache_folder=self.cache_folder,
        )
        records = []
        async for r in output:
            records.append(r)

        assert len(records) == 0

    async def test_csv_to_records_keep_incomplete(self):
        output = inventory_to_records.csv_to_records(
            self.loop,
            self.stdin,
            skip_incomplete=False,
            cache_folder=self.cache_folder,
        )
        records = []
        async for r in output:
            records.append(r)

        assert len(records) == 2
        assert records[1] == {
            'data': {
                'id': 'firefox_nightly_2017-06-16-03-02-07_56-0a1_win32_ach',
                'download': {
                    'date': '2017-06-16T03:02:07Z',
                    'mimetype': 'application/msdos-windows',
                    'size': 45678,
                    'url': (f'{ARCHIVE_URL}pub/firefox/nightly/'
                            '2017/06/2017-06-16-03-02-07-mozilla-central-l10n/'
                            'firefox-56.0a1.ach.win32.installer.exe')
                },
                'source': {
                    'product': 'firefox'
                },
                'target': {
                    'channel': 'nightly',
                    'locale': 'ach',
                    'platform': 'win32',
                    'os': 'win',
                    'version': '56.0a1'
                }
            }
        }

    async def test_csv_to_records_continues_on_error(self):
        with mock.patch('buildhub.utils.guess_mimetype',
                        side_effect=(ValueError, 'application/zip')):
            output = inventory_to_records.csv_to_records(
                self.loop,
                self.stdin,
                skip_incomplete=False,
                cache_folder=self.cache_folder,
            )
            records = []
            async for r in output:
                records.append(r)

        assert len(records) == 1  # Instead of 2 like the test above.
