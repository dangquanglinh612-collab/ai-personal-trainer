import sys
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_coach_os.services.supabase_auth import (
    AuthSnapshot,
    CoachNotAllowed,
    SupabaseAuth,
    SupabaseSettings,
)


COACH_A = "00000000-0000-4000-8000-000000000001"
COACH_B = "00000000-0000-4000-8000-000000000002"
NOW = 2_000_000_000


class SupabaseAuthTests(unittest.TestCase):
    def setUp(self):
        self.settings = SupabaseSettings("https://fixture.supabase.co", "sb_publishable_fixture")
        self.snapshot = AuthSnapshot(self.settings.url, COACH_A, NOW + 600, "fixture-access", "fixture-refresh")
        self.client = Mock()
        self.factory = Mock(return_value=self.client)
        self.core = SupabaseAuth(self.settings, {COACH_A, COACH_B}, self.factory)
        self.client.auth.get_user.return_value.user = SimpleNamespace(id=COACH_A, is_anonymous=False)
        self.client.auth.sign_in_with_password.return_value = self.response(self.snapshot)
        self.client.auth.set_session.return_value = self.response(self.snapshot)
        clock = patch("ai_coach_os.services.supabase_auth.time", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)

    @staticmethod
    def response(snapshot):
        return SimpleNamespace(session=SimpleNamespace(
            access_token=snapshot.access_token,
            refresh_token=snapshot.refresh_token,
            expires_at=snapshot.expires_at,
        ))

    def test_login_returns_verified_coach_client_and_snapshot(self):
        result = self.core.login("coach@example.invalid", "fixture-password")
        self.assertEqual(result.snapshot, self.snapshot)
        self.assertEqual(result.authenticated.coach.coach_id, COACH_A)
        self.assertIs(result.authenticated.client, self.client)
        self.client.auth.get_user.assert_called_once_with(self.snapshot.access_token)
        self.assertNotIn(self.snapshot.access_token, repr(result))
        self.assertNotIn(self.snapshot.refresh_token, repr(result))

    def test_bad_password_returns_no_result_and_redacts_sdk_error(self):
        self.client.auth.sign_in_with_password.side_effect = RuntimeError("private-sdk-message")
        with self.assertRaisesRegex(ValueError, "登录失败") as error:
            self.core.login("coach@example.invalid", "fixture-password")
        self.assertNotIn("private-sdk-message", str(error.exception))
        self.client.auth.get_user.assert_not_called()
        self.client.table.assert_not_called()

    def test_login_rejects_disallowed_and_anonymous_users(self):
        for user_id, is_anonymous in ((COACH_B, False), (COACH_A, True)):
            with self.subTest(user_id=user_id, is_anonymous=is_anonymous):
                self.client.auth.get_user.return_value.user = SimpleNamespace(
                    id=user_id, is_anonymous=is_anonymous,
                )
                with self.assertRaises(CoachNotAllowed):
                    SupabaseAuth(self.settings, {COACH_A}, self.factory).login("fixture", "fixture")
        self.client.table.assert_not_called()

    def test_restore_reuses_snapshot_before_refresh_window(self):
        result = self.core.restore(self.snapshot)
        self.assertEqual(result.snapshot, self.snapshot)
        self.client.auth.set_session.assert_called_once_with(self.snapshot.access_token, self.snapshot.refresh_token)
        self.client.auth.refresh_session.assert_not_called()
        self.client.auth.get_user.assert_called_once_with(self.snapshot.access_token)

    def test_restore_rotates_both_tokens_once_near_and_after_expiry(self):
        refreshed = replace(self.snapshot, access_token="rotated-access", refresh_token="rotated-refresh")
        self.client.auth.refresh_session.return_value = self.response(refreshed)
        for remaining in (30, -1):
            with self.subTest(remaining=remaining):
                self.client.reset_mock()
                original = replace(self.snapshot, expires_at=NOW + remaining)
                result = self.core.restore(original)
                self.assertEqual(result.snapshot, refreshed)
                self.assertIs(result.authenticated.client, self.client)
                self.assertEqual(original.refresh_token, self.snapshot.refresh_token)
                self.client.auth.refresh_session.assert_called_once_with(original.refresh_token)
                self.client.auth.set_session.assert_not_called()
                self.client.auth.get_user.assert_called_once_with(refreshed.access_token)

    def test_refresh_failure_returns_no_client_and_does_not_fall_back(self):
        self.client.auth.refresh_session.side_effect = RuntimeError("private-sdk-message")
        with self.assertRaisesRegex(ValueError, "登录状态失效") as error:
            self.core.restore(replace(self.snapshot, expires_at=NOW))
        self.assertNotIn("private-sdk-message", str(error.exception))
        self.client.auth.set_session.assert_not_called()
        self.client.auth.get_user.assert_not_called()
        self.client.table.assert_not_called()

    def test_restore_rejects_wrong_project_and_invalid_uuid_before_network(self):
        for snapshot in (
            replace(self.snapshot, project_url="https://other.supabase.co"),
            replace(self.snapshot, user_id="invalid"),
        ):
            with self.assertRaisesRegex(ValueError, "登录状态失效"):
                self.core.restore(snapshot)
        self.factory.assert_not_called()

    def test_restore_rejects_identity_change_even_if_both_coaches_are_allowed(self):
        self.client.auth.get_user.return_value.user.id = COACH_B
        with self.assertRaisesRegex(ValueError, "登录状态失效"):
            self.core.restore(self.snapshot)
        self.client.table.assert_not_called()

    def test_restore_rejects_removed_coach_before_refresh(self):
        core = SupabaseAuth(self.settings, {COACH_B}, self.factory)
        with self.assertRaises(CoachNotAllowed):
            core.restore(replace(self.snapshot, expires_at=NOW))
        self.factory.assert_not_called()

    def test_restore_rejects_expired_refresh_result(self):
        expired = replace(self.snapshot, expires_at=NOW)
        self.client.auth.refresh_session.return_value = self.response(expired)
        with self.assertRaisesRegex(ValueError, "登录状态失效"):
            self.core.restore(expired)
        self.client.auth.refresh_session.assert_called_once()
        self.client.auth.get_user.assert_not_called()

    def test_distinct_logins_on_one_core_receive_distinct_clients(self):
        other = Mock()
        other_snapshot = replace(self.snapshot, user_id=COACH_B, access_token="other-access")
        other.auth.get_user.return_value.user = SimpleNamespace(id=COACH_B, is_anonymous=False)
        other.auth.sign_in_with_password.return_value = self.response(other_snapshot)
        self.factory.side_effect = [self.client, other]
        first = self.core.login("coach-a@example.invalid", "fixture")
        second = self.core.login("coach-b@example.invalid", "fixture")
        self.assertIsNot(first.authenticated.client, second.authenticated.client)
        self.assertEqual(first.authenticated.coach.coach_id, COACH_A)
        self.assertEqual(second.authenticated.coach.coach_id, COACH_B)
        self.core.logout(first)
        self.client.auth.admin.sign_out.assert_called_once_with(first.snapshot.access_token, "local")
        self.client.auth.refresh_session.assert_not_called()
        other.auth.admin.sign_out.assert_not_called()
