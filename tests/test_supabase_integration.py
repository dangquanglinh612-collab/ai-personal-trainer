"""EXPLICITLY OPT-IN. Creates/deletes only isolated test records in a test project.

Requires RUN_SUPABASE_INTEGRATION_TESTS=1 plus project-ref and two user credentials.
Never executed as part of stage A. No Secret Key used.
"""

import os
from pathlib import Path
import sys
import unittest
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_coach_os.services.supabase_client import SupabaseSettings, SupabaseSession, SupabaseRepository


@unittest.skipUnless(os.getenv("RUN_SUPABASE_INTEGRATION_TESTS") == "1", "Real Supabase integration is opt-in")
class SupabaseIntegrationTests(unittest.TestCase):
    def test_two_users_rls_storage_transactions_and_conflicts(self):
        ref = os.environ["SUPABASE_TEST_PROJECT_REF"]
        self.assertTrue(os.environ["SUPABASE_URL"].rstrip("/") == f"https://{ref}.supabase.co",
                        "Integration URL must match the configured test ref")
        settings = SupabaseSettings.from_mapping(os.environ)
        state_a, state_b = {}, {}
        allowed = {os.environ["SUPABASE_TEST_UUID_A"], os.environ["SUPABASE_TEST_UUID_B"]}
        session_a = SupabaseSession(settings, state_a, allowed)
        session_b = SupabaseSession(settings, state_b, allowed)
        authenticated_a = session_a.login(os.environ["SUPABASE_TEST_EMAIL_A"], os.environ["SUPABASE_TEST_PASSWORD_A"])
        a = authenticated_a.client
        self.addCleanup(session_a.logout)
        b = session_b.login(os.environ["SUPABASE_TEST_EMAIL_B"], os.environ["SUPABASE_TEST_PASSWORD_B"]).client
        self.addCleanup(session_b.logout)
        self.assertNotEqual(state_a["coach_id"], state_b["coach_id"])
        repo = SupabaseRepository(authenticated_a)
        member = repo.add_member(f"stage-a-integration-{uuid4()}", 5, "test")[0]
        member_id = member["id"]
        # All child records cascade with this test-created member. Storage is separate.
        self.addCleanup(lambda: a.table("members").delete().eq("id", member_id).execute())
        first = repo.save_training_session(member_id, "2099-01-02", "", "", "", [{"exercise_name": "test"}])
        second = repo.save_training_session(member_id, "2099-01-02", "", "", "", [])
        self.assertTrue(first["should_deduct_lesson"])
        self.assertFalse(second["should_deduct_lesson"])
        self.assertEqual(a.table("members").select("remaining_lessons").eq("id", member_id).execute().data[0]["remaining_lessons"], 4)
        sid = first["session_id"]
        exercise = a.table("training_session_exercises").select("id").eq("session_id", sid).execute().data[0]
        plan = a.table("training_plans").insert({"coach_id": state_a["coach_id"], "member_id": member_id, "plan_date": "2099-01-02"}).execute().data[0]
        # Isolated future date; existing conflicting test-project appointments cause a safe failure.
        appointment = repo.create_appointment(member_id, "2099-01-02", "18:00", "19:00")[0]
        repo.create_appointment(member_id, "2099-01-02", "19:00", "20:00")
        with self.assertRaises(Exception):
            repo.create_appointment(member_id, "2099-01-02", "18:30", "19:30")
        import base64
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII=")
        photo = repo.upload_photo(member_id, sid, png, ".png", "fixture.png")[0]
        self.addCleanup(lambda: a.storage.from_("training-photos").remove([photo["object_path"]]))
        for table, row_id, field in (("members", member_id, "note"), ("training_sessions", sid, "coach_note"),
                                     ("training_session_exercises", exercise["id"], "note"),
                                     ("training_plans", plan["id"], "coach_note"),
                                     ("appointments", appointment["id"], "note"),
                                     ("training_session_photos", photo["id"], "caption")):
            with self.subTest(table=table):
                self.assertEqual(b.table(table).select("*").eq("id", row_id).execute().data, [])
                self.assertEqual(b.table(table).update({field: "forbidden"}).eq("id", row_id).execute().data, [])
                self.assertEqual(b.table(table).delete().eq("id", row_id).execute().data, [])
                self.assertTrue(a.table(table).select("id").eq("id", row_id).execute().data)
        with self.assertRaises(Exception):
            b.table("training_sessions").insert({"coach_id": state_b["coach_id"], "member_id": member_id, "training_date": "2099-01-03"}).execute()
        with self.assertRaises(Exception):
            b.table("training_session_exercises").insert({"session_id": sid, "exercise_name": "forbidden"}).execute()
        with self.assertRaises(Exception):
            b.storage.from_("training-photos").download(photo["object_path"])
        with self.assertRaises(Exception):
            b.storage.from_("training-photos").upload(photo["object_path"], png, {"upsert": "true"})
        # DELETE can return no affected objects instead of throwing; verify bytes remain.
        try:
            b.storage.from_("training-photos").remove([photo["object_path"]])
        except Exception:
            pass
        self.assertEqual(a.storage.from_("training-photos").download(photo["object_path"]), png)
        self.assertTrue(repo.photo_url(photo["object_path"]))


if __name__ == "__main__":
    unittest.main()
