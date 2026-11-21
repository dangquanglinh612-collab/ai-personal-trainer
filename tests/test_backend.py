import base64
import json
import os
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import httpx
from supabase import ClientOptions, create_client
from supabase_auth._sync import gotrue_client

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_coach_os import application, auth
from ai_coach_os.backend import create_backend, read_backend, read_supabase_config
from ai_coach_os.repositories import member_data
from ai_coach_os.repositories.contracts import CoachContext
from ai_coach_os.repositories.sqlite_read import SQLiteReadRepository
from ai_coach_os.services.supabase_client import AuthenticatedSupabase, CoachNotAllowed, SupabaseSession
from ai_coach_os.ui.views import readonly_members, shell


COACH = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
REF = "testfixture000000000"
NOW = 2_000_000_000
CONFIG = {
    "APP_DATA_BACKEND": "supabase",
    "SUPABASE_URL": f"https://{REF}.supabase.co",
    "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_fixture",
    "SUPABASE_TEST_PROJECT_REF": REF,
    "SUPABASE_ALLOWED_COACH_IDS": f"{COACH}, {OTHER}",
}


def sample_jwt(expiry):
    def encode(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    return ".".join([encode({"alg": "HS256", "typ": "JWT"}), encode({"exp": expiry}), "offline"])


class BackendTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_default_sqlite_login_and_member_list(self):
        database = sqlite3.connect(":memory:")
        self.addCleanup(database.close)
        database.executescript("""
            CREATE TABLE coaches (username TEXT, password TEXT);
            INSERT INTO coaches VALUES ('coach-fixture', 'offline');
        """)
        with patch.object(auth, "get_conn", return_value=MagicMock(wraps=database)):
            self.assertTrue(auth.verify_coach("coach-fixture", "offline"))
        ui = MagicMock(secrets={}, session_state=MagicMock())
        ui.session_state.get.return_value = "sqlite"
        ui.session_state.logged_in = True
        ui.session_state.coach_id = "coach-fixture"
        ui.session_state.page = "member_list"
        rows = [(1, "Member", 3, "", None, "", None)]
        with (
            patch.object(application, "st", ui),
            patch.object(application, "init_db") as init,
            patch.object(application, "init_session"),
            patch.object(application.pages, "member_list_page") as render,
            patch.object(member_data, "get_members_with_today_plan", return_value=rows) as query,
        ):
            application.main()
            init.assert_called_once()
            repository, coach = render.call_args.args
            self.assertIsInstance(repository, SQLiteReadRepository)
            self.assertEqual(repository.list_members(coach)[0].name, "Member")
            query.assert_called_once_with("coach-fixture")

    def test_secrets_override_environment_and_missing_file_uses_environment(self):
        secrets = MagicMock()
        secrets.get.side_effect = FileNotFoundError
        with patch.dict(os.environ, CONFIG):
            self.assertEqual(read_backend(secrets), "supabase")
            self.assertEqual(read_backend({"APP_DATA_BACKEND": "sqlite"}), "sqlite")
            self.assertEqual(read_supabase_config(secrets)[1], {COACH, OTHER})
            self.assertEqual(
                read_supabase_config({"SUPABASE_ALLOWED_COACH_IDS": COACH})[1], {COACH}
            )

    def test_invalid_config_never_constructs_client_or_initializes_sqlite(self):
        for name, bad in (
            ("APP_DATA_BACKEND", "unsupported"),
            ("SUPABASE_URL", None),
            ("SUPABASE_URL", "https://user:private@fixture.supabase.co"),
            ("SUPABASE_PUBLISHABLE_KEY", None),
            ("SUPABASE_PUBLISHABLE_KEY", "sb_secret_private"),
            ("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_"),
            ("SUPABASE_TEST_PROJECT_REF", ""),
            ("SUPABASE_TEST_PROJECT_REF", "different00000000000"),
            ("SUPABASE_ALLOWED_COACH_IDS", ""),
            ("SUPABASE_ALLOWED_COACH_IDS", "not-a-uuid"),
        ):
            with self.subTest(setting=name):
                ui = MagicMock(secrets={**CONFIG, name: bad}, session_state={})
                with (
                    patch.object(application, "st", ui),
                    patch.object(application, "init_db") as init,
                    patch.object(application, "SupabaseSession") as session,
                ):
                    application.main()
                    init.assert_not_called()
                    session.assert_not_called()
                ui.error.assert_called_once()
                self.assertIn(name, ui.error.call_args.args[0])
                self.assertNotIn("private", ui.error.call_args.args[0])

    def test_config_read_error_is_redacted(self):
        secrets = MagicMock()
        secrets.get.side_effect = ValueError("sensitive configuration content")
        with self.assertRaisesRegex(ValueError, "无法读取 Streamlit secrets"):
            read_backend(secrets)

    def test_factory_requires_authenticated_supabase_not_supplied_coach_id(self):
        with self.assertRaisesRegex(ValueError, "验证当前教练会话"):
            create_backend("supabase", sqlite_coach_id=COACH)

    def test_application_rerun_never_routes_supabase_to_sqlite(self):
        state = {"_app_backend": "sqlite", "logged_in": True, "coach_id": "sqlite-fixture"}
        ui = MagicMock(secrets=CONFIG, session_state=state)
        ui.button.return_value = False
        settings, allowed = read_supabase_config(CONFIG)
        client = MagicMock()
        client.auth.sign_in_with_password.return_value.session = SimpleNamespace(
            access_token="offline", refresh_token="offline-refresh", expires_at=4_000_000_000,
        )
        client.auth.get_user.return_value.user = SimpleNamespace(id=COACH, is_anonymous=False)
        client.auth.set_session.return_value = client.auth.sign_in_with_password.return_value
        repository = MagicMock()
        with (
            patch.object(application, "st", ui),
            patch.object(application, "init_db") as init,
            patch.object(application, "SupabaseSession",
                         side_effect=lambda *args: SupabaseSession(*args, factory=lambda _: client)),
            patch.object(application.pages, "login_page") as login_page,
            patch.object(application.pages, "member_list_page") as sqlite_page,
            patch.object(application.readonly_members, "st", ui),
            patch.object(application.readonly_members, "inject_css"),
            patch.object(application.readonly_members, "render_page_header"),
            patch.object(application, "create_backend", return_value=(repository, CoachContext(COACH))) as factory,
        ):
            application.main()
            factory.assert_not_called()
            login_page.call_args.args[0]("fixture@example.invalid", "offline")
            self.assertEqual(state["_app_backend"], "supabase")
            state["coach_id"] = OTHER
            application.main()
            verified = factory.call_args.kwargs["authenticated"]
            self.assertIs(verified.client, client)
            self.assertEqual(verified.coach, CoachContext(COACH))
            repository.list_members.assert_called_once_with(CoachContext(COACH))
            init.assert_not_called()
            sqlite_page.assert_not_called()
        self.assertEqual(state["auth_project"], settings.url)
        self.assertIn(COACH, allowed)


class SupabaseSessionTests(unittest.TestCase):
    def test_sdk_requests_and_saved_tokens_match_through_expiry_boundaries(self):
        settings, allowed = read_supabase_config(CONFIG)
        user = {"id": COACH, "aud": "authenticated", "app_metadata": {},
                "user_metadata": {}, "created_at": "2026-01-01T00:00:00Z"}
        for remaining, refreshed_ttl in ((60, 3600), (5, 3600), (-5, 3600), (-5, 9)):
            with self.subTest(remaining=remaining, refreshed_ttl=refreshed_ttl):
                requests = []
                original = sample_jwt(NOW + remaining)
                rotated = sample_jwt(NOW + refreshed_ttl)
                state = {"auth_project": settings.url, "auth_user": {"id": COACH},
                         "auth_expires_at": NOW + remaining,
                         "access_token": original, "refresh_token": "fixture-original"}

                def handle(request):
                    requests.append(request)
                    if request.url.path == "/auth/v1/user":
                        return httpx.Response(200, json=user)
                    if request.url.path == "/auth/v1/token":
                        return httpx.Response(200, json={
                            "access_token": rotated, "refresh_token": "fixture-rotated",
                            "expires_at": NOW + refreshed_ttl, "expires_in": refreshed_ttl,
                            "token_type": "bearer", "user": user,
                        })
                    if request.url.path == "/rest/v1/members":
                        return httpx.Response(200, json=[])
                    if request.url.path == "/auth/v1/logout":
                        return httpx.Response(204)
                    raise AssertionError("Unexpected SDK route")

                with (
                    httpx.Client(transport=httpx.MockTransport(handle)) as transport,
                    patch.object(gotrue_client.time, "time", return_value=NOW),
                    patch("ai_coach_os.services.supabase_auth.time", return_value=NOW),
                ):
                    def factory(config):
                        return create_client(config.url, config.publishable_key, options=ClientOptions(
                            httpx_client=transport, persist_session=False, auto_refresh_token=False,
                        ))

                    session = SupabaseSession(settings, state, allowed, factory)
                    authenticated = session.restore()
                    with patch.object(authenticated.client.auth, "get_user") as get_user:
                        repository, coach = create_backend("supabase", authenticated=authenticated)
                        repository.list_members(coach)
                        get_user.assert_not_called()
                    self.assertEqual(sum(req.url.path == "/auth/v1/token" for req in requests),
                                     int(remaining <= 30))
                    self.assertTrue(requests[-1].headers["Authorization"] == "Bearer " + state["access_token"])
                    self.assertTrue(state["access_token"] == (original if remaining > 30 else rotated))
                    self.assertTrue(state["refresh_token"] == (
                        "fixture-original" if remaining > 30 else "fixture-rotated"
                    ))
                    with self.assertRaises(PermissionError):
                        repository.list_members(CoachContext(OTHER))
                    if remaining <= 30 and refreshed_ttl > 30:
                        SupabaseSession(settings, state, allowed, factory).restore()
                        self.assertEqual(sum(req.url.path == "/auth/v1/token" for req in requests), 1)
                    session.logout()
                    self.assertEqual(requests[-1].url.path, "/auth/v1/logout")
                    self.assertEqual(requests[-1].url.params.get("scope"), "local")
                    self.assertTrue(requests[-1].headers["Authorization"] == "Bearer " + (
                        original if remaining > 30 else rotated
                    ))
                    self.assertEqual(sum(req.url.path == "/auth/v1/token" for req in requests),
                                     int(remaining <= 30))
                    self.assertEqual(state, {})

    def test_denies_unauthorized_and_anonymous_users_without_writing_profiles(self):
        settings, _ = read_supabase_config(CONFIG)
        client = MagicMock()
        client.auth.sign_in_with_password.return_value.session = SimpleNamespace(
            access_token="offline", refresh_token="offline-refresh", expires_at=4_000_000_000,
        )
        for user_id, anonymous in ((OTHER, False), (COACH, True)):
            with self.subTest(anonymous=anonymous):
                client.auth.get_user.return_value.user = SimpleNamespace(id=user_id, is_anonymous=anonymous)
                state = {}
                with self.assertRaises(CoachNotAllowed):
                    SupabaseSession(settings, state, {COACH}, lambda _: client).login("fixture", "offline")
                self.assertEqual(state, {})
                client.table.assert_not_called()

    def test_changed_identity_or_project_invalidates_state(self):
        settings, allowed = read_supabase_config(CONFIG)
        for project_matches in (True, False):
            with self.subTest(project_matches=project_matches):
                client = MagicMock()
                client.auth.set_session.return_value.session = SimpleNamespace(
                    access_token="offline", refresh_token="offline-refresh", expires_at=4_000_000_000,
                )
                client.auth.get_user.return_value.user = SimpleNamespace(id=OTHER, is_anonymous=False)
                state = {"auth_project": settings.url if project_matches else "other-project",
                         "auth_user": {"id": COACH}, "auth_expires_at": 4_000_000_000,
                         "access_token": "offline", "refresh_token": "offline-refresh"}
                factory = MagicMock(return_value=client)
                with self.assertRaisesRegex(ValueError, "登录状态失效"):
                    SupabaseSession(settings, state, allowed, factory).restore()
                self.assertEqual(state, {})
                if not project_matches:
                    factory.assert_not_called()

    def test_two_authenticated_users_and_logout_are_isolated(self):
        settings, allowed = read_supabase_config(CONFIG)
        sessions = []
        for user_id in (COACH, OTHER):
            client = MagicMock()
            client.auth.sign_in_with_password.return_value.session = SimpleNamespace(
                access_token=f"fixture-{user_id}", refresh_token="offline-refresh",
                expires_at=4_000_000_000,
            )
            client.auth.get_user.return_value.user = SimpleNamespace(id=user_id, is_anonymous=False)
            session = SupabaseSession(settings, {}, allowed, MagicMock(return_value=client))
            authenticated = session.login("fixture", "offline")
            repository, coach = create_backend("supabase", authenticated=authenticated)
            self.assertEqual(coach, CoachContext(user_id))
            repository.list_members(coach)
            client.table.return_value.select.return_value.eq.assert_called_once_with("coach_id", user_id)
            sessions.append(session)

        first, second = sessions
        first.logout()
        self.assertEqual(first.state, {})
        self.assertEqual(second.state["auth_user"]["id"], OTHER)
        self.assertTrue(second.state["logged_in"])
        second.authenticated.client.auth.admin.sign_out.assert_not_called()


class SupabaseMemberViewsTests(unittest.TestCase):
    def setUp(self):
        self.state = {"_app_backend": "supabase", "logged_in": True, "coach_id": OTHER}
        self.ui = MagicMock(secrets=CONFIG, session_state=self.state)
        self.ui.button.return_value = False
        self.client = MagicMock()
        self.query = self.client.table.return_value.select.return_value
        self.query.eq.return_value = self.query
        self.query.limit.return_value = self.query
        self.query.order.return_value = self.query
        self.summary = dict(
            id=5, name="测试会员", remaining_lessons=0, goal="力量训练",
            last_training_date="2026-11-18", ai_reminder="先热身",
        )
        authenticated = AuthenticatedSupabase(self.client, CoachContext(COACH))
        for target, attribute, options in (
            (application, "st", {"new": self.ui}),
            (readonly_members, "st", {"new": self.ui}),
            (shell, "st", {"new": self.ui}),
            (readonly_members, "inject_css", {}),
            (application, "init_db", {"side_effect": AssertionError("SQLite startup forbidden")}),
            (application, "run_sqlite", {"side_effect": AssertionError("SQLite fallback forbidden")}),
            (application, "SupabaseSession", {}),
            (sqlite3, "connect", {"side_effect": AssertionError("SQLite access forbidden")}),
        ):
            replacement = patch.object(target, attribute, **options)
            result = replacement.start()
            self.addCleanup(replacement.stop)
            if attribute == "SupabaseSession":
                result.return_value.restore.return_value = authenticated

    def test_directory_open_detail_and_return(self):
        class State(dict):
            def __setattr__(self, name, value):
                self[name] = value

        self.ui.session_state = state = State(self.state)
        self.query.execute.return_value.data = [self.summary]
        application.main()
        navigation = next(call for call in self.ui.button.call_args_list if call.args == ("查看详情",))
        navigation.kwargs["on_click"](*navigation.kwargs["args"])
        self.assertEqual(state["selected_member_id"], 5)

        self.ui.text.reset_mock()
        self.query.eq.reset_mock()
        self.query.execute.return_value.data = [
            dict(self.summary, created_at="2026-01-02T03:04:05Z", avatar_emoji="🏋️",
                 phone="555-0102", note="注意休息"),
        ]
        application.main()
        self.assertEqual(
            [call.args[0] for call in self.ui.text.call_args_list],
            ["测试会员", "🏋️", "2026-01-02T03:04:05Z", "0", "力量训练",
             "2026-11-18", "先热身", "555-0102", "注意休息"],
        )
        self.assertEqual([call.args for call in self.query.eq.call_args_list],
                         [("coach_id", COACH), ("id", 5)])

        self.ui.button.side_effect = lambda label, **kwargs: label == "返回会员列表"
        self.query.execute.reset_mock()
        application.main()
        self.ui.rerun.assert_called_once()
        self.query.execute.assert_not_called()
        self.assertEqual(state["page"], "member_list")
        self.assertIsNone(state["selected_member_id"])

    def test_detail_missing_invalid_and_network_failure_never_fall_back(self):
        self.state.update(page="member_detail", selected_member_id=5)
        self.query.execute.return_value.data = []
        application.main()
        self.ui.info.assert_called_once_with("未找到会员，或当前账号无权查看。")

        self.state["selected_member_id"] = "invalid"
        self.query.execute.reset_mock()
        application.main()
        self.ui.warning.assert_called_once_with("会员编号无效，请返回会员列表重新选择。")
        self.query.execute.assert_not_called()

        self.state["selected_member_id"] = 5
        self.query.execute.side_effect = ConnectionError("redacted backend error")
        application.main()
        self.ui.error.assert_called_once_with("无法加载会员详情，请检查网络连接后重试。")
        self.ui.text.assert_not_called()
        application.run_sqlite.assert_not_called()
        sqlite3.connect.assert_not_called()
