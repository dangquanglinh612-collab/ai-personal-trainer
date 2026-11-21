import os
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from threading import Event
from unittest.mock import Mock, call, patch

from fastapi.testclient import TestClient

SRC = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, SRC)

from ai_coach_os.repositories.contracts import (  # noqa: E402
    CoachContext, CoachReadRepository, ExerciseOption, MemberDetail, MemberSummary,
    TrainingHistoryExercise, TrainingHistoryItem,
)
from ai_coach_os.services.supabase_auth import (  # noqa: E402
    AuthenticatedSupabase, AuthResult, AuthSnapshot, CoachNotAllowed, SupabaseAuth,
)
from ai_coach_os.web.app import create_app  # noqa: E402
from ai_coach_os.web.sessions import InMemorySessionStore  # noqa: E402


API = "/api/v1"
ORIGIN = "https://fixture.example"
WRITE_HEADERS = {"Origin": ORIGIN, "X-AI-Coach-Request": "1"}
COOKIE = "__Host-ai_coach_session"
COACH_A = "00000000-0000-4000-8000-000000000001"
COACH_B = "00000000-0000-4000-8000-000000000002"
PROJECT = "https://fixture.supabase.co"


def verified(user_id, snapshot=None):
    snapshot = snapshot or AuthSnapshot(PROJECT, user_id, 4_000_000_000,
                                       "fixture-access", "fixture-refresh")
    return AuthResult(AuthenticatedSupabase(Mock(), CoachContext(user_id)), snapshot)


class WebAPITests(unittest.TestCase):
    def setUp(self):
        self.auth = Mock(spec=SupabaseAuth)
        self.auth.login.side_effect = lambda email, password: verified(
            COACH_A if email == "a@example.invalid" else COACH_B
        )
        self.auth.restore.side_effect = lambda snapshot: verified(snapshot.user_id, snapshot)
        self.summary = MemberSummary(1, "Member A", 10, "Strength", None, None,
                                     today_plan_available=False)
        self.detail = MemberDetail(1, "Member A", 10, "Strength", None, None, "", "", None, None)
        self.repository = Mock(spec=CoachReadRepository)
        self.repository.list_members.return_value = [self.summary]
        self.repository.get_member.side_effect = (
            lambda coach, member_id: self.detail if (coach.coach_id, member_id) == (COACH_A, 1) else None
        )
        self.factory = Mock(return_value=self.repository)
        self.app = create_app(auth=self.auth, repository_factory=self.factory, origin=ORIGIN)
        self.client = self.browser()

    def browser(self, app=None):
        client = TestClient(app or self.app, base_url=ORIGIN)
        self.addCleanup(client.close)
        return client

    def login(self, client=None, email="a@example.invalid", headers=None):
        return (client or self.client).post(
            f"{API}/auth/login",
            json={"email": email, "password": "fixture-password"},
            headers=WRITE_HEADERS if headers is None else headers,
        )

    def assert_error(self, response, status, code):
        self.assertEqual(response.status_code, status)
        self.assertFalse(response.json()["success"])
        self.assertIsNone(response.json()["data"])
        self.assertEqual(response.json()["error"]["code"], code)
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_login_me_and_secure_cookie_hide_tokens(self):
        response = self.login()
        self.assertEqual(response.json(), {
            "success": True, "data": {"id": COACH_A}, "error": None,
        })
        flags = [part.strip().lower() for part in response.headers["set-cookie"].split(";")[1:]]
        for flag in ("httponly", "secure", "path=/", "samesite=lax"):
            self.assertIn(flag, flags)
        self.assertFalse(any(flag.startswith("domain=") for flag in flags))
        session_id = self.client.cookies[COOKIE]
        self.assertGreaterEqual(len(session_id), 43)
        current = self.client.get(f"{API}/auth/me")
        self.assertEqual(current.json(), response.json())
        self.auth.restore.assert_called_once()
        self.factory.assert_not_called()
        for secret in ("fixture-access", "fixture-refresh", "fixture-password"):
            self.assertNotIn(secret, response.text + current.text + response.headers["set-cookie"])

    def test_wrong_password_and_unlisted_coach_receive_no_session(self):
        for failure, status, code in (
            (ValueError("internal-fixture"), 401, "LOGIN_FAILED"),
            (CoachNotAllowed("internal-fixture"), 403, "COACH_NOT_ALLOWED"),
        ):
            with self.subTest(status=status):
                self.auth.login.side_effect = failure
                response = self.login()
                self.assert_error(response, status, code)
                self.assertNotIn("internal-fixture", response.text)
                self.assertNotIn("set-cookie", response.headers)
        self.auth.restore.assert_not_called()

    def test_all_five_reads_require_a_session(self):
        for path in ("auth/me", "members", "members/1", "exercises", "members/1/training-sessions"):
            with self.subTest(path=path):
                self.assert_error(self.client.get(f"{API}/{path}"), 401, "UNAUTHORIZED")
        self.auth.restore.assert_not_called()
        self.factory.assert_not_called()

    def test_save_training_is_scoped_validated_and_same_origin(self):
        path = f"{API}/members/1/training-sessions"
        entry = {"training_date": "2026-11-21", "exercises": [{"exercise_name": "Squat"}]}
        save = Mock(return_value={"session_id": 17, "should_deduct_lesson": True})
        self.repository.save_training_session = save
        self.assert_error(self.client.post(path, headers=WRITE_HEADERS, json=entry), 401, "UNAUTHORIZED")
        self.login()
        self.assert_error(self.client.post(path, json=entry), 403, "ORIGIN_REJECTED")
        for invalid in ({"coach_id": COACH_B}, {"session_id": 4}, {"exercises": []},
                        {"exercises": [{"exercise_name": "  "}]}, {"training_date": "invalid"}):
            self.assert_error(self.client.post(path, json=entry | invalid, headers=WRITE_HEADERS),
                              422, "INVALID_REQUEST")
        self.assert_error(self.client.post(path.replace("/1/", "/2/"), headers=WRITE_HEADERS,
                                           json=entry), 404, "MEMBER_NOT_FOUND")
        save.assert_not_called()
        response = self.client.post(path, json=entry, headers=WRITE_HEADERS)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"], save.return_value)
        self.assertEqual(save.call_count, 1)
        self.assertEqual(save.call_args.args[0], 1)
        self.assertEqual(save.call_args.args[-1][0]["exercise_name"], "Squat")

    def test_origin_and_custom_header_are_required_for_login_and_logout(self):
        for headers in ({}, {"Origin": ORIGIN}, {**WRITE_HEADERS, "Origin": "https://elsewhere.example"}):
            with self.subTest(headers=headers):
                self.assert_error(self.login(headers=headers), 403, "ORIGIN_REJECTED")
                response = self.client.post(f"{API}/auth/logout", headers=headers)
                self.assert_error(response, 403, "ORIGIN_REJECTED")
                self.assertNotIn("access-control-allow-origin", response.headers)
        self.auth.login.assert_not_called()
        self.auth.logout.assert_not_called()

    def test_logout_removes_cookie_and_invalidates_sid_even_on_remote_failure(self):
        for failure in (None, RuntimeError("internal-fixture"), ValueError("remote-failure")):
            with self.subTest(failure=failure):
                self.login()
                old_id = self.client.cookies[COOKIE]
                self.auth.logout.reset_mock(side_effect=True)
                self.auth.logout.side_effect = failure
                response = self.client.post(f"{API}/auth/logout", headers=WRITE_HEADERS)
                self.assertEqual(response.json(), {"success": True, "data": None, "error": None})
                self.assertIn("Max-Age=0", response.headers["set-cookie"])
                self.auth.logout.assert_called_once()
                self.assertNotIn(COOKIE, self.client.cookies)
                with_cookie = self.client.get(f"{API}/auth/me", headers={"Cookie": f"{COOKIE}={old_id}"})
                self.assert_error(with_cookie, 401, "UNAUTHORIZED")

    def test_refresh_failure_invalidates_only_the_current_session(self):
        self.login()
        old_id = self.client.cookies[COOKIE]
        self.auth.restore.side_effect = ValueError("refresh-token-fixture")
        response = self.client.get(f"{API}/members")
        self.assert_error(response, 401, "UNAUTHORIZED")
        self.assertNotIn("refresh-token-fixture", response.text)
        self.assertNotIn(COOKIE, self.client.cookies)
        self.assert_error(self.client.get(f"{API}/auth/me", headers={"Cookie": f"{COOKIE}={old_id}"}),
                          401, "UNAUTHORIZED")
        self.auth.restore.assert_called_once()
        self.factory.assert_not_called()

    def test_member_list_and_detail_use_repository_contracts(self):
        self.login()
        response = self.client.get(f"{API}/members")
        self.assertEqual(response.json()["data"][0]["name"], "Member A")
        self.assertFalse(response.json()["data"][0]["today_plan_available"])
        self.repository.list_members.assert_called_once_with(CoachContext(COACH_A))
        detail = self.client.get(f"{API}/members/1").json()["data"]
        self.assertEqual(set(detail), {
            "id", "name", "remaining_lessons", "goal", "last_training_date", "ai_reminder",
            "phone", "note", "created_at", "avatar_emoji",
        })
        self.repository.get_member.assert_called_once_with(CoachContext(COACH_A), 1)
        first, second = self.factory.call_args_list
        self.assertIsNot(first.args[0].client, second.args[0].client)

    def test_invalid_id_or_client_coach_parameters_do_not_reach_repository(self):
        self.login()
        for path in ("members/0", "members/-1", "members/no-id", f"members/{2**63}"):
            self.assert_error(self.client.get(f"{API}/{path}"), 422, "INVALID_REQUEST")
        for path in ("members", "members/1", "members/1/training-sessions"):
            response = self.client.get(f"{API}/{path}", params={"coach_id": COACH_B})
            self.assert_error(response, 422, "INVALID_QUERY")
        self.factory.assert_not_called()

    def test_isolated_coaches_and_missing_member_share_not_found_response(self):
        self.login()
        other = self.browser()
        self.login(other, "b@example.invalid")
        self.assertNotEqual(self.client.cookies[COOKIE], other.cookies[COOKIE])
        self.assertEqual(other.get(f"{API}/auth/me").json()["data"], {"id": COACH_B})
        missing = self.client.get(f"{API}/members/2")
        foreign = other.get(f"{API}/members/1")
        self.assert_error(foreign, 404, "MEMBER_NOT_FOUND")
        self.assertEqual(foreign.json(), missing.json())
        denied_history = other.get(f"{API}/members/1/training-sessions")
        self.assertEqual(denied_history.json(), missing.json())
        self.repository.list_training_history.assert_not_called()
        self.client.post(f"{API}/auth/logout", headers=WRITE_HEADERS)
        self.assertEqual(other.get(f"{API}/auth/me").json()["data"]["id"], COACH_B)

    def test_login_rotates_sid_when_switching_accounts(self):
        self.login()
        old_id = self.client.cookies[COOKIE]
        self.login(email="b@example.invalid")
        self.assertNotEqual(old_id, self.client.cookies[COOKIE])
        stale = self.browser().get(f"{API}/auth/me", headers={"Cookie": f"{COOKIE}={old_id}"})
        self.assert_error(stale, 401, "UNAUTHORIZED")
        self.assertEqual(self.client.get(f"{API}/auth/me").json()["data"]["id"], COACH_B)

    def test_exercises_and_training_history_use_verified_repositories(self):
        self.login()
        self.repository.list_exercises.return_value = [ExerciseOption(5, "Squat")]
        exercise = TrainingHistoryExercise("Squat", "20", "2", "8", None, None, 0)
        self.repository.list_training_history.return_value = [
            TrainingHistoryItem(7, "2026-01-02", "", "Note", None, None, (exercise,)),
        ]
        exercises = self.client.get(f"{API}/exercises")
        self.assertEqual(exercises.json()["data"], [{"id": 5, "name": "Squat"}])
        self.repository.list_exercises.assert_called_once_with(CoachContext(COACH_A))
        self.repository.reset_mock()
        history = self.client.get(f"{API}/members/1/training-sessions")
        self.assertEqual(history.json()["data"][0]["exercises"][0]["exercise_name"], "Squat")
        self.assertEqual(self.repository.mock_calls, [
            call.get_member(CoachContext(COACH_A), 1),
            call.list_training_history(CoachContext(COACH_A), 1),
        ])

    def test_unexpected_errors_and_invalid_payload_are_redacted(self):
        invalid = self.client.post(f"{API}/auth/login", json={
            "email": "a@example.invalid", "password": "fixture-password", "coach_id": "fixture-user",
        }, headers=WRITE_HEADERS)
        self.assert_error(invalid, 422, "INVALID_REQUEST")
        self.assertNotIn("fixture-password", invalid.text)
        self.auth.login.assert_not_called()
        self.login()
        self.repository.list_members.side_effect = RuntimeError("internal database credential")
        failure = self.client.get(f"{API}/members")
        self.assert_error(failure, 500, "INTERNAL_ERROR")
        self.assertNotIn("internal database credential", failure.text)

    def test_real_repository_uses_the_verified_client_without_refresh(self):
        data_client = Mock()
        result = AuthResult(AuthenticatedSupabase(data_client, CoachContext(COACH_A)),
                            verified(COACH_A).snapshot)
        self.auth.restore.side_effect = None
        self.auth.restore.return_value = result
        data_client.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value.data = []
        browser = self.browser(create_app(auth=self.auth, origin=ORIGIN))
        self.login(browser)
        self.assertEqual(browser.get(f"{API}/members").json()["data"], [])
        data_client.auth.get_user.assert_not_called()
        data_client.auth.refresh_session.assert_not_called()
        data_client.table.return_value.select.return_value.eq.assert_called_once_with("coach_id", COACH_A)

    def test_concurrent_reads_restore_from_the_latest_snapshot(self):
        entered = Event()
        waiting = Event()
        release = Event()
        old = verified(COACH_A)
        rotated = replace(old.snapshot, refresh_token="rotated-refresh")
        observations = []

        class ObservedStore(InMemorySessionStore):
            @contextmanager
            def locked(self, session_id):
                if entered.is_set():
                    waiting.set()
                with super().locked(session_id) as snapshot:
                    yield snapshot

        def restore(snapshot):
            observations.append(snapshot.refresh_token)
            if snapshot == old.snapshot:
                entered.set()
                if not release.wait(5):
                    raise RuntimeError("Timed out waiting for the second request")
            return verified(COACH_A, rotated)

        self.auth.restore.side_effect = restore
        app = create_app(auth=self.auth, store=ObservedStore(), origin=ORIGIN)
        first, second = self.browser(app), self.browser(app)
        self.login(first)
        headers = {"Cookie": f"{COOKIE}={first.cookies[COOKIE]}"}
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = pool.submit(first.get, f"{API}/auth/me")
            try:
                self.assertTrue(entered.wait(5))
                next_request = pool.submit(second.get, f"{API}/auth/me", headers=headers)
                self.assertTrue(waiting.wait(5))
                self.assertEqual(observations, ["fixture-refresh"])
            finally:
                release.set()
            self.assertEqual(pending.result().status_code, 200)
            self.assertEqual(next_request.result().status_code, 200)
        self.assertEqual(observations, ["fixture-refresh", "rotated-refresh"])

    def test_session_idle_timeout_and_absolute_timeout(self):
        for idle, lifetime in ((10, 60), (60, 10)):
            with self.subTest(idle=idle), patch("ai_coach_os.web.sessions.monotonic", return_value=100) as clock:
                app = create_app(auth=self.auth, store=InMemorySessionStore(idle, lifetime), origin=ORIGIN)
                browser = self.browser(app)
                self.login(browser)
                clock.return_value = 110
                self.assert_error(browser.get(f"{API}/auth/me"), 401, "UNAUTHORIZED")

    def test_logout_waits_for_refresh_and_invalidates_the_rotated_session(self):
        entered = Event()
        queued = Event()
        release = Event()
        original = verified(COACH_A)
        rotated = replace(original.snapshot, refresh_token="rotated-refresh")

        class ObservedStore(InMemorySessionStore):
            @contextmanager
            def locked(self, session_id):
                if entered.is_set():
                    queued.set()
                with super().locked(session_id) as snapshot:
                    yield snapshot

        def restore(snapshot):
            if snapshot == original.snapshot:
                entered.set()
                if not release.wait(5):
                    raise RuntimeError("Timed out waiting for logout")
            return verified(COACH_A, rotated)

        self.auth.restore.side_effect = restore
        app = create_app(auth=self.auth, store=ObservedStore(), origin=ORIGIN)
        first, second = self.browser(app), self.browser(app)
        self.login(first)
        headers = {**WRITE_HEADERS, "Cookie": f"{COOKIE}={first.cookies[COOKIE]}"}
        with ThreadPoolExecutor(max_workers=2) as pool:
            read = pool.submit(first.get, f"{API}/auth/me")
            try:
                self.assertTrue(entered.wait(5))
                logout = pool.submit(second.post, f"{API}/auth/logout", headers=headers)
                self.assertTrue(queued.wait(5))
            finally:
                release.set()
            self.assertEqual(read.result().status_code, 200)
            self.assertEqual(logout.result().status_code, 200)
        self.assertEqual(self.auth.logout.call_args.args[0].snapshot, rotated)
        self.assert_error(first.get(f"{API}/auth/me"), 401, "UNAUTHORIZED")

    def test_missing_supabase_configuration_fails_without_streamlit_or_sqlite(self):
        result = subprocess.run([sys.executable, "-B", "-c", """
import os, sys
sys.modules.update(streamlit=None, sqlite3=None)
os.environ["APP_DATA_BACKEND"] = "sqlite"
from ai_coach_os.web.app import create_app
try:
    create_app()
except ValueError as error:
    assert "SUPABASE_URL" in str(error)
else:
    raise AssertionError("Expected a configuration error")
"""], env={**os.environ, "PYTHONPATH": SRC, "SUPABASE_URL": ""}, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
