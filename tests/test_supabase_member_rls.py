"""Opt-in member SELECT checks in the separately confirmed test project."""

import os
from pathlib import Path
import sys
import unittest
from uuid import UUID
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_coach_os.backend import create_backend, read_supabase_config
from ai_coach_os.services.supabase_client import SupabaseSession


def connect_test_coaches():
    settings, allowed = read_supabase_config({
        "SUPABASE_URL": os.environ["SUPABASE_TEST_URL"],
        "SUPABASE_PUBLISHABLE_KEY": os.environ["SUPABASE_TEST_PUBLISHABLE_KEY"],
        "SUPABASE_TEST_PROJECT_REF": os.environ["SUPABASE_TEST_PROJECT_REF"],
        "SUPABASE_ALLOWED_COACH_IDS": os.environ["SUPABASE_ALLOWED_COACH_IDS"],
    })
    fixtures = [
        (
            str(UUID(os.environ[f"SUPABASE_TEST_UUID_{coach}"])),
            int(os.environ[f"SUPABASE_TEST_MEMBER_ID_{coach}"]),
            os.environ[f"SUPABASE_TEST_EMAIL_{coach}"],
            os.environ[f"SUPABASE_TEST_PASSWORD_{coach}"],
        )
        for coach in ("A", "B")
    ]
    first, second = fixtures
    if (
        first[0] == second[0] or first[1] == second[1]
        or first[2].strip().casefold() == second[2].strip().casefold()
        or any(
            coach_id not in allowed or not 0 < member_id < 2**63 or not email.strip() or not password
            for coach_id, member_id, email, password in fixtures
        )
    ):
        raise ValueError("Invalid test account or member fixtures")

    coaches = []
    for coach_id, member_id, email, password in fixtures:
        authenticated = SupabaseSession(settings, {}, allowed).login(email, password)
        if authenticated.coach.coach_id != coach_id:
            raise ValueError("Authenticated UUID does not match fixture")
        coaches.append((authenticated, member_id))
    return coaches


class SupabaseMemberRLSPreflightTests(unittest.TestCase):
    def test_missing_or_disallowed_fixtures_stop_before_auth(self):
        test_ref = "testfixture000000000"
        coach_id = "11111111-1111-4111-8111-111111111111"
        other_id = "22222222-2222-4222-8222-222222222222"
        environment = {
            "SUPABASE_TEST_URL": f"https://{test_ref}.supabase.co",
            "SUPABASE_TEST_PROJECT_REF": test_ref,
            "SUPABASE_TEST_PUBLISHABLE_KEY": "sb_publishable_fixture",
            "SUPABASE_ALLOWED_COACH_IDS": coach_id,
            "SUPABASE_TEST_UUID_A": coach_id,
            "SUPABASE_TEST_UUID_B": other_id,
            "SUPABASE_TEST_MEMBER_ID_A": "5",
            "SUPABASE_TEST_MEMBER_ID_B": "6",
            "SUPABASE_TEST_EMAIL_A": "coach-a@example.invalid",
            "SUPABASE_TEST_EMAIL_B": "coach-b@example.invalid",
            "SUPABASE_TEST_PASSWORD_A": "offline-a",
            "SUPABASE_TEST_PASSWORD_B": "offline-b",
        }
        with patch(f"{__name__}.SupabaseSession") as session:
            with patch.dict(os.environ, environment, clear=True):
                with self.assertRaises(ValueError):
                    connect_test_coaches()
                del os.environ["SUPABASE_TEST_MEMBER_ID_B"]
                with self.assertRaises(KeyError):
                    connect_test_coaches()
                os.environ["SUPABASE_TEST_URL"] = "https://wrongproject.supabase.co"
                with self.assertRaises(ValueError):
                    connect_test_coaches()
            session.assert_not_called()


@unittest.skipUnless(
    os.getenv("RUN_SUPABASE_MEMBER_RLS_SELECT_TESTS") == "1",
    "Read-only Supabase member RLS test is opt-in",
)
class SupabaseMemberRLSSelectTests(unittest.TestCase):
    def test_member_repository_and_database_enforce_two_coach_isolation(self):
        try:
            coaches = connect_test_coaches()
        except Exception:
            raise AssertionError(
                "Preflight or Auth failed; confirm test project, credentials, allowlist and member fixtures."
            ) from None

        for index, (authenticated, member_id) in enumerate(coaches):
            other, other_member_id = coaches[1 - index]
            with self.subTest(coach=("A", "B")[index]):
                repository, coach = create_backend("supabase", authenticated=authenticated)
                try:
                    detail = repository.get_member(coach, member_id)
                    visible_ids = {member.id for member in repository.list_members(coach)}
                    foreign_detail = repository.get_member(coach, other_member_id)
                    client = authenticated.client
                    raw_visible = client.table("members").select("id,coach_id").execute().data
                    raw_foreign_id = (
                        client.table("members").select("id").eq("id", other_member_id).execute().data
                    )
                    raw_foreign_owner = (
                        client.table("members").select("id").eq("coach_id", other.coach.coach_id).execute().data
                    )
                    raw_any_foreign_owner = (
                        client.table("members").select("id").neq("coach_id", coach.coach_id).limit(1).execute().data
                    )
                except Exception:
                    raise AssertionError(
                        "Member SELECT failed; confirm test fixtures, network and Data API access."
                    ) from None
                self.assertTrue(detail is not None and detail.id == member_id, "Own member fixture not visible")
                self.assertTrue(member_id in visible_ids, "Own member fixture missing from repository list")
                self.assertTrue(foreign_detail is None, "Foreign member visible through repository detail")
                self.assertTrue(other_member_id not in visible_ids, "Foreign fixture visible through repository list")
                self.assertTrue(any(row["id"] == member_id for row in raw_visible), "Own fixture missing from Data API")
                self.assertTrue(all(row["coach_id"] == coach.coach_id for row in raw_visible),
                                "Unscoped Data API SELECT returned a foreign owner")
                self.assertFalse(raw_foreign_id, "Foreign member visible through the Data API")
                self.assertFalse(raw_foreign_owner, "Changing the owner filter exposed foreign data")
                self.assertFalse(raw_any_foreign_owner, "Data API returned a member owned by a different coach")
