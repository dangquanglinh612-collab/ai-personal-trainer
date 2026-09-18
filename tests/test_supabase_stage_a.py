"""Stage A tests require neither credentials, a network, nor Supabase SDK."""

import copy
from contextlib import redirect_stdout
import importlib.util
import io
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
try:
    import streamlit
except ModuleNotFoundError:
    sys.modules["streamlit"] = types.SimpleNamespace(secrets={}, session_state={}, set_page_config=lambda **kwargs: None)

from ai_coach_os.repositories import database
from ai_coach_os.services.supabase_client import SupabaseSettings, SupabaseSession, SupabaseRepository, create_public_client

spec = importlib.util.spec_from_file_location("migration", ROOT / "scripts/migrate_sqlite_to_supabase.py")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)
A = "11111111-1111-4111-8111-111111111111"
B = "22222222-2222-4222-8222-222222222222"
MAPPING = {"wenwen": A, "numb": B}


class MemoryRemote:
    """Only a test double: exercises insert-only migration and resumability."""

    def __init__(self):
        self.rows = {t: [] for t in ("profiles",) + migration.TABLES}
        self.auth = MagicMock()
        self.auth.admin.get_user_by_id.side_effect = lambda user_id: types.SimpleNamespace(user=types.SimpleNamespace(id=user_id))
        self.storage = MagicMock()
        self.storage.get_bucket.return_value = {"public": False}
        self.rpc = MagicMock()
        self.fail_table = None

    def table(self, table):
        remote = self

        class Query:
            count_only = False
            inserted = None
            start = 0
            end = 499

            def select(self, *args, **kwargs):
                self.count_only = kwargs.get("head", False)
                return self

            def order(self, *args):
                return self

            def range(self, start, end):
                self.start, self.end = start, end
                return self

            def insert(self, row):
                self.inserted = copy.deepcopy(row)
                return self

            def execute(self):
                if self.inserted is not None:
                    if table == remote.fail_table:
                        raise RuntimeError("simulated insert failure")
                    remote.rows[table].append(self.inserted)
                return types.SimpleNamespace(data=copy.deepcopy(remote.rows[table][self.start:self.end + 1]), count=len(remote.rows[table]))

        return Query()


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "test.db"
        with patch.object(database, "DB_NAME", str(self.db)):
            database.init_db()

    def plan(self, mapping=MAPPING):
        return migration.build_plan(self.db, mapping, self.root)

    def sql(self, statement, args=()):
        conn = sqlite3.connect(self.db)
        try:
            cursor = conn.execute(statement, args)
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def test_read_only_counts_mapping_and_legacy(self):
        before = self.db.read_bytes()
        plan = self.plan()
        self.assertEqual(plan["errors"], [])
        self.assertEqual(plan["counts"]["members"], 5)
        self.assertEqual(plan["counts"]["lesson_plans"], 3)
        self.assertEqual(plan["rows"]["members"][0]["coach_id"], A)
        self.assertNotIn("coaches", plan["rows"])
        self.assertNotIn("password", str(plan["rows"]))
        self.assertEqual(before, self.db.read_bytes())

    def test_mapping_missing_invalid_or_merged_fails(self):
        for mapping in ({}, {"wenwen": "bad", "numb": B}, {"wenwen": A, "numb": A}):
            self.assertTrue(self.plan(mapping)["errors"])

    def test_missing_database_not_created(self):
        path = self.root / "missing.db"
        with self.assertRaises(ValueError):
            migration.build_plan(path, MAPPING)
        self.assertFalse(path.exists())

    def test_unexpected_columns_block_silent_loss(self):
        self.sql("ALTER TABLE members ADD COLUMN unexpected TEXT")
        self.assertIn("未映射字段", str(self.plan()["errors"]))

    def test_real_avatar_field_is_preserved(self):
        self.sql("ALTER TABLE members ADD COLUMN avatar_emoji TEXT DEFAULT '🙂'")
        self.assertEqual(self.plan()["rows"]["members"][0]["avatar_emoji"], "🙂")

    def test_orphan_fk_is_rejected(self):
        self.sql("INSERT INTO training_session_exercises(session_id,exercise_name) VALUES(999,'test')")
        self.assertIn("孤儿 FK", str(self.plan()["errors"]))

    def test_cross_coach_member_is_rejected(self):
        self.sql("INSERT INTO training_sessions(coach_id,member_id,training_date) VALUES('numb',1,'2026-09-14')")
        self.assertIn("跨教练", str(self.plan()["errors"]))

    def test_bad_date_and_status_rejected(self):
        self.sql("INSERT INTO appointments(coach_id,member_id,appointment_date,start_time,end_time,status) VALUES('wenwen',1,'bad','18:00','19:00','invalid')")
        errors = str(self.plan()["errors"])
        self.assertIn("日期/时间", errors)
        self.assertIn("status", errors)

    def test_timezone_empty_dates(self):
        self.assertIsNone(migration.normalize_value("last_training_date", ""))
        self.assertEqual(migration.normalize_value("created_at", "2026-09-14T08:00:00"), "2026-09-14T00:00:00+00:00")
        self.assertEqual(migration.normalize_value("start_time", "18:00"), "18:00:00")

    def test_appointment_boundaries_cancelled_and_overlap(self):
        for start, end, status in (("18:00", "19:00", "scheduled"), ("19:00", "20:00", "completed"), ("18:30", "19:30", "cancelled")):
            self.sql("INSERT INTO appointments(coach_id,member_id,appointment_date,start_time,end_time,status) VALUES('wenwen',1,'2026-09-14',?,?,?)", (start, end, status))
        self.assertFalse(self.plan()["errors"])
        self.sql("UPDATE appointments SET status='scheduled' WHERE status='cancelled'")
        self.assertIn("冲突", str(self.plan()["errors"]))

    def test_photo_outside_allowed_directory_rejected(self):
        path = self.root / "outside.jpg"
        path.write_bytes(b"fixture")
        with self.assertRaises(ValueError):
            migration.photo_file(self.root, str(path))

    def test_photo_mapping_deterministic_without_local_mutation(self):
        folder = self.root / "uploads/training_photos"
        folder.mkdir(parents=True)
        image = folder / "fixture.jpg"
        image.write_bytes(b"image fixture")
        session_id = self.sql("INSERT INTO training_sessions(coach_id,member_id,training_date) VALUES('wenwen',1,'2026-09-14')")
        self.sql("INSERT INTO training_session_photos(coach_id,member_id,session_id,file_path) VALUES('wenwen',1,?,?)", (session_id, "uploads/training_photos/fixture.jpg"))
        one, two = self.plan(), self.plan()
        self.assertFalse(one["errors"])
        photo = one["rows"]["training_session_photos"][0]
        self.assertTrue(photo["object_path"].startswith(f"{A}/1/{session_id}/"))
        self.assertNotIn("file_path", photo)
        self.assertEqual(one["rows"], two["rows"])
        self.assertEqual(image.read_bytes(), b"image fixture")

    def test_dry_run_never_imports_sdk_or_connects(self):
        mapping = self.root / "map.json"
        mapping.write_text(__import__("json").dumps(MAPPING), encoding="utf-8")
        with patch.dict(sys.modules, {"supabase": None}), redirect_stdout(io.StringIO()):
            self.assertEqual(migration.main(["--dry-run", "--sqlite", str(self.db), "--coach-map", str(mapping)]), 0)

    def test_execute_refuses_validation_errors_before_client_calls(self):
        client = MagicMock()
        with self.assertRaises(ValueError):
            migration.execute_plan(self.plan({}), client)
        self.assertFalse(client.mock_calls)

    def test_equivalent_remote_timestamps_compare_equal(self):
        self.assertTrue(migration._same_row({"created_at": "2026-09-14T08:00:00+08:00"}, {"created_at": "2026-09-14T00:00:00Z"}))

    def test_execute_insert_then_resume_skips_identical_rows(self):
        remote = MemoryRemote()
        plan = self.plan()
        first = migration.execute_plan(plan, remote)
        self.assertTrue(first["success"])
        self.assertEqual(first["inserted"]["members"], 5)
        second = migration.execute_plan(plan, remote)
        self.assertTrue(second["success"])
        self.assertEqual(sum(second["inserted"].values()), 0)
        self.assertEqual(remote.rpc.call_args.args, ("realign_migration_sequences",))

    def test_remote_unrelated_records_abort_before_writes(self):
        remote = MemoryRemote()
        remote.rows["members"] = [{"id": 999, "name": "unrelated"}]
        with self.assertRaisesRegex(ValueError, "非本次迁移"):
            migration.execute_plan(self.plan(), remote)
        self.assertEqual(remote.rows["profiles"], [])

    def test_remote_same_id_changed_content_is_not_overwritten(self):
        remote = MemoryRemote()
        plan = self.plan()
        remote.rows["members"] = [dict(plan["rows"]["members"][0], name="different")]
        with self.assertRaisesRegex(ValueError, "禁止覆盖"):
            migration.execute_plan(plan, remote)
        self.assertEqual(remote.rows["members"][0]["name"], "different")
        self.assertEqual(remote.rows["profiles"], [])

    def test_partial_insert_failure_reports_row_and_can_resume(self):
        remote = MemoryRemote()
        remote.fail_table = "members"
        plan = self.plan()
        failed = migration.execute_plan(plan, remote)
        self.assertFalse(failed["success"])
        self.assertEqual(failed["failed_rows"][0]["table"], "members")
        self.assertEqual(len(remote.rows["exercise_library"]), 20)
        remote.fail_table = None
        self.assertTrue(migration.execute_plan(plan, remote)["success"])

    def test_public_bucket_aborts_before_business_writes(self):
        remote = MemoryRemote()
        remote.storage.get_bucket.return_value = {"public": True}
        with self.assertRaisesRegex(ValueError, "private"):
            migration.execute_plan(self.plan(), remote)
        self.assertFalse(any(remote.rows.values()))

    def test_remote_count_mismatch_never_claims_success(self):
        remote = MemoryRemote()
        original_table = remote.table

        def wrong_count(table):
            query = original_table(table)
            original_execute = query.execute

            def execute():
                response = original_execute()
                if query.count_only:
                    response.count += 1
                return response

            query.execute = execute
            return query

        remote.table = wrong_count
        self.assertFalse(migration.execute_plan(self.plan(), remote)["success"])


class SupabaseAdapterTests(unittest.TestCase):
    def setUp(self):
        self.settings = SupabaseSettings.from_mapping({"SUPABASE_URL": "https://test.supabase.co", "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_fixture"})
        self.state = {}
        self.client = MagicMock()
        self.client.auth.get_user.return_value.user.id = A
        response = types.SimpleNamespace(session=types.SimpleNamespace(access_token="new-access", refresh_token="new-refresh"))
        self.client.auth.sign_in_with_password.return_value = response
        self.client.auth.set_session.return_value = response
        self.factory = MagicMock(return_value=self.client)
        self.session = SupabaseSession(self.settings, self.state, self.factory)

    def test_application_rejects_secret_key(self):
        with self.assertRaises(ValueError):
            SupabaseSettings.from_mapping({"SUPABASE_URL": self.settings.url, "SUPABASE_PUBLISHABLE_KEY": "sb_secret_never"})
        self.assertNotIn("sb_publishable_fixture", repr(self.settings))
        with self.assertRaises(ValueError):
            SupabaseSettings(self.settings.url, "sb_secret_bypass_attempt")

    def test_stage_a_backend_flag_cannot_silently_write_sqlite(self):
        from ai_coach_os import application
        ui = MagicMock()
        ui.secrets = {"APP_DATA_BACKEND": "supabase"}
        with patch.object(application, "st", ui), patch.object(application, "init_db") as init:
            application.main()
        init.assert_not_called()
        ui.error.assert_called_once()

    def test_sdk_factory_is_local_and_uncached_when_installed(self):
        try:
            from supabase import ClientOptions  # noqa: F401
        except ImportError:
            self.skipTest("Install project dependencies for real SDK construction check")
        with patch("socket.socket.connect", side_effect=AssertionError("Network forbidden")):
            first = create_public_client(self.settings)
            second = create_public_client(self.settings)
        self.assertIsNot(first, second)

    def test_login_uses_verified_uuid_and_clears_previous_widgets(self):
        self.state.update({"coach_id": B, "training_parse_draft": "other", "plan_widget": "other"})
        self.session.login("coach@example.invalid", "not-a-real-password")
        self.assertEqual(self.state["coach_id"], A)
        self.assertNotIn("training_parse_draft", self.state)
        self.assertNotIn("plan_widget", self.state)
        self.client.table.assert_called_with("profiles")

    def test_restore_persists_rotated_tokens(self):
        self.state.update(access_token="old", refresh_token="old-refresh", coach_id=A)
        self.session.restore()
        self.client.auth.set_session.assert_called_once_with("old", "old-refresh")
        self.assertEqual(self.state["refresh_token"], "new-refresh")

    def test_refresh_failure_clears_all_state_and_redacts_exception(self):
        self.state.update(access_token="old", refresh_token="old", training_parse_draft="private")
        self.client.auth.set_session.side_effect = RuntimeError("secret_internal")
        with self.assertRaisesRegex(ValueError, "登录状态失效") as error:
            self.session.restore()
        self.assertNotIn("secret_internal", str(error.exception))
        self.assertEqual(self.state, {})

    def test_logout_clears_even_when_signout_fails(self):
        self.session.login("a", "b")
        self.client.auth.sign_out.side_effect = RuntimeError("offline")
        self.session.logout()
        self.assertEqual(self.state, {})

    def test_distinct_browser_states_do_not_share_tokens(self):
        other_state = {"coach_id": B}
        other = SupabaseSession(self.settings, other_state, self.factory)
        self.session.login("a", "b")
        self.assertEqual(other.state, {"coach_id": B})

    def test_training_uses_one_transaction_rpc(self):
        repo = SupabaseRepository(self.client)
        repo.save_training_session(1, "2026-09-14", "", "", "", [])
        self.client.rpc.assert_called_once()
        self.assertNotIn("coach_id", self.client.rpc.call_args.args[1])
        self.client.table.assert_not_called()

    def test_storage_cross_owner_path_rejected_before_network(self):
        repo = SupabaseRepository(self.client)
        with self.assertRaises(ValueError):
            repo.photo_url(f"{B}/1/1/a.jpg")
        self.client.storage.from_.assert_not_called()

    def test_storage_url_has_short_expiry(self):
        repo = SupabaseRepository(self.client)
        repo.photo_url(f"{A}/1/1/a.jpg")
        self.client.storage.from_.return_value.create_signed_url.assert_called_once_with(f"{A}/1/1/a.jpg", 300)


class SQLContractTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("pglast"), "Install dev extra for SQL parser check")
    def test_postgresql_sql_and_plpgsql_parse(self):
        from pglast import parse_sql, parse_plpgsql
        for name in ("schema.sql", "indexes.sql", "rls.sql", "storage.sql", "rpc.sql"):
            sql = (ROOT / "supabase" / name).read_text(encoding="utf-8")
            with self.subTest(file=name):
                self.assertTrue(parse_sql(sql))
        self.assertTrue(parse_plpgsql((ROOT / "supabase/rpc.sql").read_text(encoding="utf-8")))

    def test_every_table_has_explicit_rls_policies(self):
        sql = (ROOT / "supabase/rls.sql").read_text(encoding="utf-8")
        for table in ("profiles",) + migration.TABLES:
            self.assertIn(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY", sql)
            for op in (("select",) if table == "exercise_library" else ("select", "insert", "update", "delete")):
                self.assertIn(f"CREATE POLICY {table}_{op} ", sql)
        self.assertNotIn("FOR ALL", sql)
        self.assertNotIn("exercise_library_insert", sql)

    def test_composite_fks_and_appointment_exclusion(self):
        sql = (ROOT / "supabase/schema.sql").read_text(encoding="utf-8")
        self.assertEqual(sql.count("REFERENCES public.members(id, coach_id)"), 6)
        self.assertIn("REFERENCES public.training_sessions(id, member_id, coach_id)", sql)
        self.assertIn("EXCLUDE USING gist", sql)
        self.assertIn("'[)'", sql)
        self.assertIn("WHERE (status <> 'cancelled')", sql)

    def test_rpc_is_invoker_and_sequence_admin_only(self):
        sql = (ROOT / "supabase/rpc.sql").read_text(encoding="utf-8")
        self.assertNotIn("SECURITY DEFINER", sql)
        self.assertIn("FOR UPDATE", sql)
        self.assertIn("FROM PUBLIC, anon, authenticated", sql)

    def test_storage_private_and_all_operations_owner_scoped(self):
        sql = (ROOT / "supabase/storage.sql").read_text(encoding="utf-8")
        self.assertIn("'training-photos','training-photos',false", sql)
        self.assertEqual(sql.count("CREATE POLICY coach_photos_"), 4)
        self.assertEqual(sql.count("(select auth.uid())::text"), 5)


if __name__ == "__main__":
    unittest.main()
