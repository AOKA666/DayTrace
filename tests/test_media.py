import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from daytrace.domain import Observation
from daytrace.media import MediaIdleGuard, MediaPlaybackMonitor, source_matches_process


class FakeSource:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def snapshot(self, rules, expected_hwnd=None, read_title=True):
        self.calls.append((rules, expected_hwnd, read_title))
        return self.result


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.media = MediaPlaybackMonitor(autostart=False)
        self.guard = MediaIdleGuard()

    def test_conservative_process_matching(self):
        self.assertTrue(source_matches_process('chrome.exe', 'Chrome.exe'))
        self.assertTrue(source_matches_process('SpotifyAB.SpotifyMusic!Spotify', 'Spotify.exe'))
        self.assertFalse(source_matches_process('spotify.exe', 'Code.exe'))
        self.assertFalse(source_matches_process('notchromehelper', 'chrome.exe'))

    def test_foreground_playback_suppresses_input_idle(self):
        self.media._replace(['chrome.exe'])
        initial = Observation('active', 'chrome.exe', 'chrome', None, 7)
        refreshed = Observation('active', 'chrome.exe', 'chrome', 'Video - Chrome', 7)
        source = FakeSource(refreshed)
        result, idle, playing = self.guard.resolve(source, initial, 6000, 5000, self.media, 10000, [])
        self.assertEqual(result, refreshed)
        self.assertEqual(idle, 0)
        self.assertTrue(playing)
        self.assertEqual(source.calls, [([], 7, True)])

    def test_background_or_paused_media_does_not_suppress_idle(self):
        self.media._replace(['spotify.exe'])
        initial = Observation('active', 'Code.exe', 'code', None, 8)
        source = FakeSource(initial)
        result, idle, playing = self.guard.resolve(source, initial, 6000, 5000, self.media, 10000, [])
        self.assertEqual((result, idle, playing), (initial, 6000, False))
        self.assertEqual(source.calls, [])

    def test_exclusion_found_during_media_refresh_wins(self):
        self.media._replace(['chrome.exe'])
        initial = Observation('active', 'chrome.exe', 'chrome', None, 7)
        source = FakeSource(Observation('excluded'))
        result, idle, playing = self.guard.resolve(source, initial, 6000, 5000, self.media, 10000, [])
        self.assertEqual(result.state, 'excluded')
        self.assertEqual(idle, 0)
        self.assertFalse(playing)

    def test_stale_media_state_is_not_used(self):
        self.media._replace(['chrome.exe'])
        self.media._updated = time.monotonic() - 4
        self.assertFalse(self.media.playing_for('chrome.exe'))

    def test_playback_end_starts_a_new_idle_clock(self):
        observation = Observation('active', 'chrome.exe', 'chrome', 'Video', 7)
        source = FakeSource(observation)
        self.media._replace(['chrome.exe'])
        self.guard.resolve(source, observation, 240000, 300000, self.media, 10000, [])
        self.media._replace([])
        result, idle, playing = self.guard.resolve(
            source, observation, 600000, 300000, self.media, 11000, [])
        self.assertEqual(result, observation)
        self.assertEqual(idle, 1000)
        self.assertFalse(playing)
        _, idle, _ = self.guard.resolve(
            source, observation, 900000, 300000, self.media, 311000, [])
        self.assertEqual(idle, 301000)

    def test_short_playback_is_not_backdated_when_raw_idle_is_below_threshold(self):
        observation = Observation('active', 'chrome.exe', 'chrome', 'Video', 7)
        source = FakeSource(observation)
        self.media._replace(['chrome.exe'])
        self.guard.resolve(source, observation, 120000, 300000, self.media, 120000, [])
        self.media._replace([])
        _, idle, _ = self.guard.resolve(
            source, observation, 121000, 300000, self.media, 121000, [])
        self.assertEqual(idle, 1000)

    def test_fresh_input_clears_playback_grace(self):
        observation = Observation('active', 'chrome.exe', 'chrome', 'Video', 7)
        source = FakeSource(observation)
        self.media._replace(['chrome.exe'])
        self.guard.resolve(source, observation, 400000, 300000, self.media, 10000, [])
        self.media._replace([])
        _, idle, _ = self.guard.resolve(source, observation, 100, 300000, self.media, 11000, [])
        self.assertEqual(idle, 100)
        self.assertIsNone(self.guard.last_playing_ms)


if __name__ == '__main__':
    unittest.main()
