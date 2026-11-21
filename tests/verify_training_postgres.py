"""Verify the checked-in RPC/RLS in a disposable loopback PostgreSQL cluster."""

import os
import secrets
import shutil
import socket
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = Path(os.getenv("COACH_TEST_PG_BIN") or
           Path(shutil.which("initdb") or "C:/Program Files/PostgreSQL/18/bin/initdb.exe").parent)


def main():
    with tempfile.TemporaryDirectory(prefix="coach-postgres-") as folder:
        root = Path(folder)
        data = root / "pgdata"
        password = secrets.token_urlsafe(32)
        env = {k: v for k, v in os.environ.items()
               if not k.upper().startswith(("PG", "SUPABASE_"))}
        env.update(PGPASSWORD=password, PGCLIENTENCODING="UTF8")

        def run(tool, *args, sql=None):
            executable = os.getenv("COACH_TEST_PSQL") if tool == "psql" else None
            if tool == "pg_ctl" and args[-1] == "start":
                subprocess.run([str(BIN / tool), *args], stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               check=True, env=env, timeout=75)
                return ""
            return subprocess.run([executable or str(BIN / tool), *args], input=sql, text=True,
                                  encoding="utf8", errors="replace", env=env,
                                  capture_output=True, check=True).stdout.strip()

        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = str(reservation.getsockname()[1])
        password_file = root / "init-password"
        password_file.write_text(password, encoding="ascii")
        run("initdb", "-D", data, "-U", "fixture_admin", "-A", "scram-sha-256",
            "--encoding=UTF8", "--locale=C", f"--pwfile={password_file}")
        password_file.unlink()
        run("pg_ctl", "-D", data, "-l", root / "server.log", "-o",
            f"-h 127.0.0.1 -p {port}", "-w", "start")
        try:
            def query(sql):
                return run("psql", "-XAtq", "-v", "ON_ERROR_STOP=1", "-h", "127.0.0.1",
                           "-p", port, "-U", "fixture_admin", "-d", "postgres", sql=sql)

            query("""
                CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role;
                CREATE SCHEMA auth; CREATE TABLE auth.users(id uuid PRIMARY KEY);
                CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS
                    $$ SELECT current_setting('fixture.uid', true)::uuid $$;
                GRANT USAGE ON SCHEMA auth TO authenticated;
            """)
            for filename in ("schema.sql", "rls.sql", "rpc.sql"):
                query((ROOT / "supabase" / filename).read_text(encoding="utf8"))
            a, b = (f"00000000-0000-4000-8000-{i:012d}" for i in (1, 2))
            query(f"""INSERT INTO auth.users VALUES ('{a}'), ('{b}');
                INSERT INTO members(coach_id,name,remaining_lessons) VALUES
                    ('{a}','Fixture A',2), ('{b}','Fixture B',2);""")
            owner = f"SET ROLE authenticated; SET fixture.uid='{a}';"
            save = """SELECT public.save_training_session_transaction(
                1,'2026-11-21','','','','[{"exercise_name":"Fixture"}]') ->> 'should_deduct_lesson';"""
            with ThreadPoolExecutor(2) as pool:
                assert sorted(pool.map(query, [owner + save] * 2)) == ["false", "true"]
            assert query(owner + "SELECT remaining_lessons FROM members WHERE id=1;") == "1"
            assert query(owner + "SELECT count(*) FROM training_session_exercises;") == "2"
            foreign = f"SET ROLE authenticated; SET fixture.uid='{b}';"
            try:
                query(foreign + save)
            except subprocess.CalledProcessError as exc:
                assert "Member not available" in exc.stderr
            else:
                raise AssertionError("Cross-coach save allowed")
            assert query(foreign + "SELECT count(*) FROM training_sessions;") == "0"
            assert query(owner + "SELECT count(*) FROM training_sessions;") == "2"
            print("PASS: PostgreSQL concurrent saves, one deduction, two actions, owner isolation.")
        finally:
            run("pg_ctl", "-D", data, "-m", "fast", "-w", "stop")


if __name__ == "__main__":
    main()
