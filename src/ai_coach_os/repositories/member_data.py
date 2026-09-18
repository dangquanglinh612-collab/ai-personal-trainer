"""SQLite repositories for members, training records, and photos."""

import logging
import re
import sqlite3
import uuid
from datetime import date, datetime
from pathlib import Path

from . import database
from .database import get_conn


logger = logging.getLogger(__name__)


def _ensure_member_belongs_to_coach(cursor, coach_id, member_id):
    cursor.execute(
        "SELECT 1 FROM members WHERE coach_id = ? AND id = ? LIMIT 1",
        (coach_id, member_id),
    )
    if cursor.fetchone() is None:
        raise ValueError("会员不存在或不属于当前教练。")


def get_members_with_today_plan(coach_id):
    conn = get_conn()
    try:
        c = conn.cursor()
        today = str(date.today())
        c.execute("""
        SELECT
            m.id,
            m.name,
            m.remaining_lessons,
            m.goal,
            m.last_training_date,
            m.ai_reminder,
            lp.start_time
        FROM members m
        LEFT JOIN appointments lp
            ON lp.id = (
                SELECT a.id
                FROM appointments a
                WHERE a.member_id = m.id
                  AND a.coach_id = m.coach_id
                  AND a.appointment_date = ?
                  AND a.status = 'scheduled'
                ORDER BY a.start_time ASC, a.id ASC
                LIMIT 1
            )
        WHERE m.coach_id = ?
        ORDER BY
            CASE WHEN lp.start_time IS NOT NULL THEN 0 ELSE 1 END,
            lp.start_time ASC,
            m.id DESC
        """, (today, coach_id))
        return c.fetchall()
    finally:
        conn.close()


def add_member(coach_id, name, remaining_lessons, goal):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("""
        INSERT INTO members (
            coach_id, name, remaining_lessons, goal, phone, note, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            coach_id, name, remaining_lessons, goal, "", "",
            datetime.now().isoformat(timespec="seconds")
        ))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_member_by_id(coach_id, member_id):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("""
        SELECT
            id, name, remaining_lessons, goal, last_training_date,
            ai_reminder, phone, note
        FROM members
        WHERE coach_id = ? AND id = ?
        """, (coach_id, member_id))
        return c.fetchone()
    finally:
        conn.close()


def update_member_contact_note(coach_id, member_id, phone, note):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("""
        UPDATE members
        SET phone = ?, note = ?
        WHERE coach_id = ? AND id = ?
        """, (phone, note, coach_id, member_id))
        if c.rowcount != 1:
            raise ValueError("会员不存在或不属于当前教练。")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_body_measurement(coach_id, member_id, record_date, height, weight,
                            body_fat="", waist="", hip="", note=""):
    conn = get_conn()
    try:
        c = conn.cursor()
        _ensure_member_belongs_to_coach(c, coach_id, member_id)
        c.execute(
            """
            INSERT INTO body_measurements (
                coach_id, member_id, record_date, height, weight,
                body_fat, waist, hip, note, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                coach_id,
                member_id,
                str(record_date),
                height,
                weight,
                body_fat,
                waist,
                hip,
                note,
                datetime.now().isoformat(timespec="seconds"),
            )
        )
        measurement_id = c.lastrowid
        conn.commit()
        return measurement_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_latest_body_measurement(coach_id, member_id):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT id, record_date, height, weight, body_fat,
                   waist, hip, note, created_at
            FROM body_measurements
            WHERE coach_id = ? AND member_id = ?
            ORDER BY record_date DESC, id DESC
            LIMIT 1
            """,
            (coach_id, member_id)
        )
        return c.fetchone()
    finally:
        conn.close()


def get_body_measurements_for_member(coach_id, member_id):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT id, record_date, height, weight, body_fat,
                   waist, hip, note, created_at
            FROM body_measurements
            WHERE coach_id = ? AND member_id = ?
            ORDER BY record_date DESC, id DESC
            """,
            (coach_id, member_id)
        )
        return c.fetchall()
    finally:
        conn.close()


def add_member_lessons(coach_id, member_id, added_lessons):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("""
        UPDATE members
        SET remaining_lessons = remaining_lessons + ?
        WHERE coach_id = ? AND id = ?
        """, (added_lessons, coach_id, member_id))
        if c.rowcount != 1:
            raise ValueError("会员不存在或不属于当前教练。")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_today_plan_for_member(coach_id, member_id):
    conn = get_conn()
    try:
        c = conn.cursor()
        today = str(date.today())
        c.execute("""
        SELECT start_time, status, note
        FROM appointments
        WHERE coach_id = ?
          AND member_id = ?
          AND appointment_date = ?
          AND status != 'cancelled'
        ORDER BY start_time ASC, id ASC
        LIMIT 1
        """, (coach_id, member_id, today))
        return c.fetchone()
    finally:
        conn.close()


def get_exercise_options():
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("SELECT id, name FROM exercise_library ORDER BY id ASC")
        return c.fetchall()
    finally:
        conn.close()


def parse_training_text(raw_text, exercise_options):
    """将粘贴文本尽可能解析成结构化动作；任何坏行都降级为可手动修改的记录。"""
    if not raw_text or not exercise_options:
        return []

    option_names = sorted(exercise_options, key=lambda item: len(item[1]), reverse=True)
    parsed_rows = []

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        try:
            exercise_id, exercise_name = None, line
            matched_name = False
            for option_id, option_name in option_names:
                if option_name in line:
                    exercise_id, exercise_name = option_id, option_name
                    matched_name = True
                    break

            weight_match = re.search(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(kg|公斤|斤)\b", line, re.IGNORECASE)
            chinese_sets = re.search(r"(\d+)\s*组", line)
            chinese_reps = re.search(r"(\d+)\s*次", line)
            compact = re.search(r"(?<!\d)(\d+)\s*[xX×*]\s*(\d+)(?!\d)", line)
            rpe_match = re.search(r"RPE\s*[:：]?\s*(\d+(?:\.\d+)?)", line, re.IGNORECASE)

            weight = ""
            if weight_match:
                weight = f"{weight_match.group(1)}{weight_match.group(2)}"

            sets = chinese_sets.group(1) if chinese_sets else (compact.group(1) if compact else "")
            reps = chinese_reps.group(1) if chinese_reps else (compact.group(2) if compact else "")
            rpe = rpe_match.group(1) if rpe_match else ""

            if matched_name:
                remainder = line.replace(exercise_name, "", 1)
                for match in (weight_match, chinese_sets, chinese_reps, compact, rpe_match):
                    if match:
                        remainder = remainder.replace(match.group(0), "", 1)
                note = re.sub(r"\s+", " ", remainder).strip(" ,，;；")
            else:
                note = f"{line}；动作库未匹配，请人工选择"

            parsed_rows.append({
                "exercise_id": exercise_id,
                "exercise_name": exercise_name,
                "weight": weight,
                "sets": sets,
                "reps": reps,
                "rpe": rpe if rpe in {str(i) for i in range(1, 11)} else "",
                "note": note,
            })
        except Exception:
            exercise_id, exercise_name = None, line
            parsed_rows.append({
                "exercise_id": exercise_id,
                "exercise_name": exercise_name,
                "weight": "",
                "sets": "",
                "reps": "",
                "rpe": "",
                "note": f"{line}；动作库未匹配，请人工选择",
            })

    return parsed_rows[:10]


def has_training_session_on_date(coach_id, member_id, training_date):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT 1 FROM training_sessions
            WHERE coach_id = ? AND member_id = ? AND training_date = ?
            LIMIT 1
            """,
            (coach_id, member_id, str(training_date))
        )
        return c.fetchone() is not None
    finally:
        conn.close()


def _insert_training_exercises(cursor, session_id, exercise_rows):
    for sort_order, row in enumerate(exercise_rows):
        cursor.execute(
            """
            INSERT INTO training_session_exercises (
                session_id, exercise_id, exercise_name, weight,
                sets, reps, rpe, note, sort_order
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                row.get("exercise_id"),
                row.get("exercise_name", ""),
                row.get("weight", ""),
                row.get("sets", ""),
                row.get("reps", ""),
                row.get("rpe", ""),
                row.get("note", ""),
                sort_order,
            )
        )


def create_training_session(coach_id, member_id, training_date, member_feedback,
                            coach_note, raw_paste_text, exercise_rows):
    conn = get_conn()
    try:
        c = conn.cursor()
        _ensure_member_belongs_to_coach(c, coach_id, member_id)
        c.execute(
            """
            INSERT INTO training_sessions (
                coach_id, member_id, training_date, member_feedback,
                coach_note, raw_paste_text, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                coach_id, member_id, str(training_date), member_feedback,
                coach_note, raw_paste_text,
                datetime.now().isoformat(timespec="seconds"),
            )
        )
        session_id = c.lastrowid
        _insert_training_exercises(c, session_id, exercise_rows)
        conn.commit()
        return session_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _update_member_after_training(cursor, coach_id, member_id, training_date,
                                  should_deduct_lesson):
    if should_deduct_lesson:
        cursor.execute(
            """
            UPDATE members
            SET last_training_date = ?,
                remaining_lessons = CASE
                    WHEN remaining_lessons > 0 THEN remaining_lessons - 1
                    ELSE 0
                END
            WHERE coach_id = ? AND id = ?
            """,
            (str(training_date), coach_id, member_id),
        )
    else:
        cursor.execute(
            """
            UPDATE members SET last_training_date = ?
            WHERE coach_id = ? AND id = ?
            """,
            (str(training_date), coach_id, member_id),
        )
    if cursor.rowcount != 1:
        raise ValueError("会员不存在或不属于当前教练。")


def save_training_session(coach_id, member_id, training_date, member_feedback,
                          coach_note, raw_paste_text, exercise_rows):
    """原子创建训练记录、动作明细并更新会员课时与最后训练日期。"""
    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        c = conn.cursor()
        _ensure_member_belongs_to_coach(c, coach_id, member_id)
        c.execute(
            """
            SELECT 1 FROM training_sessions
            WHERE coach_id = ? AND member_id = ? AND training_date = ?
            LIMIT 1
            """,
            (coach_id, member_id, str(training_date)),
        )
        should_deduct_lesson = c.fetchone() is None
        c.execute(
            """
            INSERT INTO training_sessions (
                coach_id, member_id, training_date, member_feedback,
                coach_note, raw_paste_text, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                coach_id, member_id, str(training_date), member_feedback,
                coach_note, raw_paste_text,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        session_id = c.lastrowid
        _insert_training_exercises(c, session_id, exercise_rows)
        _update_member_after_training(
            c, coach_id, member_id, training_date, should_deduct_lesson
        )
        conn.commit()
        return session_id, should_deduct_lesson
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_training_session(coach_id, session_id, training_date, member_feedback,
                            coach_note, raw_paste_text, exercise_rows):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute(
            """
            UPDATE training_sessions
            SET training_date = ?, member_feedback = ?, coach_note = ?, raw_paste_text = ?
            WHERE id = ? AND coach_id = ?
            """,
            (
                str(training_date), member_feedback, coach_note,
                raw_paste_text, session_id, coach_id,
            )
        )
        if c.rowcount != 1:
            raise ValueError("训练记录不存在或不属于当前教练。")
        c.execute("DELETE FROM training_session_exercises WHERE session_id = ?", (session_id,))
        _insert_training_exercises(c, session_id, exercise_rows)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def finish_training_and_update_member(coach_id, member_id, training_date, should_deduct_lesson):
    conn = get_conn()
    try:
        c = conn.cursor()
        _update_member_after_training(
            c, coach_id, member_id, training_date, should_deduct_lesson
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def save_uploaded_training_photos(coach_id, member_id, session_id,
                                  uploaded_files, caption=""):
    if not uploaded_files:
        return []

    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT 1
            FROM training_sessions
            WHERE id = ? AND coach_id = ? AND member_id = ?
            LIMIT 1
            """,
            (session_id, coach_id, member_id)
        )
        if c.fetchone() is None:
            raise ValueError("找不到当前教练和会员对应的训练记录。")
    finally:
        conn.close()

    project_root = database.PROJECT_ROOT
    relative_upload_dir = Path("uploads") / "training_photos"
    upload_dir = project_root / relative_upload_dir
    upload_dir.mkdir(parents=True, exist_ok=True)

    allowed_extensions = {".jpg", ".jpeg", ".png"}
    safe_coach_id = re.sub(r"[^A-Za-z0-9_-]", "_", str(coach_id)) or "coach"
    saved_photo_ids = []

    for uploaded_file in uploaded_files:
        original_filename = Path(str(getattr(uploaded_file, "name", ""))).name
        extension = Path(original_filename).suffix.lower()
        if extension not in allowed_extensions:
            continue

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
        stored_filename = (
            f"{safe_coach_id}_{member_id}_{session_id}_"
            f"{timestamp}_{uuid.uuid4().hex}{extension}"
        )
        relative_file_path = relative_upload_dir / stored_filename
        absolute_file_path = project_root / relative_file_path
        photo_conn = None

        try:
            file_bytes = uploaded_file.getvalue()
            absolute_file_path.write_bytes(file_bytes)

            photo_conn = get_conn()
            photo_cursor = photo_conn.cursor()
            photo_cursor.execute(
                """
                INSERT INTO training_session_photos (
                    coach_id, member_id, session_id, file_path,
                    original_filename, caption, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    coach_id,
                    member_id,
                    session_id,
                    relative_file_path.as_posix(),
                    original_filename,
                    caption,
                    datetime.now().isoformat(timespec="seconds"),
                )
            )
            saved_photo_id = photo_cursor.lastrowid
            photo_conn.commit()
            saved_photo_ids.append(saved_photo_id)
        except Exception:
            logger.exception(
                "Failed to save training photo for coach=%s member=%s session=%s",
                coach_id,
                member_id,
                session_id,
            )
            if photo_conn is not None:
                photo_conn.rollback()
            try:
                absolute_file_path.unlink(missing_ok=True)
            except OSError:
                pass
        finally:
            if photo_conn is not None:
                photo_conn.close()

    return saved_photo_ids


def get_training_photos_for_session(coach_id, member_id, session_id):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT id, file_path, original_filename, caption, created_at
            FROM training_session_photos
            WHERE coach_id = ? AND member_id = ? AND session_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (coach_id, member_id, session_id)
        )
        return c.fetchall()
    finally:
        conn.close()


def get_training_sessions_for_member(coach_id, member_id):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT id, training_date, member_feedback, coach_note, raw_paste_text, created_at
            FROM training_sessions
            WHERE coach_id = ? AND member_id = ?
            ORDER BY training_date DESC, id DESC
            """,
            (coach_id, member_id)
        )
        return c.fetchall()
    finally:
        conn.close()


def get_exercises_for_session(coach_id, session_id):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT e.exercise_name, e.weight, e.sets, e.reps,
                   e.rpe, e.note, e.sort_order
            FROM training_session_exercises e
            INNER JOIN training_sessions s ON s.id = e.session_id
            WHERE e.session_id = ? AND s.coach_id = ?
            ORDER BY e.sort_order ASC, e.id ASC
            """,
            (session_id, coach_id)
        )
        return c.fetchall()
    finally:
        conn.close()


def get_recent_training_context(coach_id, member_id, limit=5):
    """读取指定教练名下会员的最近训练及动作明细。"""
    try:
        safe_limit = max(1, int(limit))
    except (TypeError, ValueError):
        safe_limit = 5

    conn = get_conn()
    conn.row_factory = sqlite3.Row
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT id, training_date, member_feedback, coach_note,
                   raw_paste_text, created_at
            FROM training_sessions
            WHERE coach_id = ? AND member_id = ?
            ORDER BY training_date DESC, id DESC
            LIMIT ?
            """,
            (coach_id, member_id, safe_limit)
        )
        sessions = []
        for session_row in c.fetchall():
            session = dict(session_row)
            c.execute(
                """
                SELECT e.exercise_name, e.weight, e.sets, e.reps,
                       e.rpe, e.note, e.sort_order
                FROM training_session_exercises e
                INNER JOIN training_sessions s ON s.id = e.session_id
                WHERE e.session_id = ? AND s.coach_id = ? AND s.member_id = ?
                ORDER BY e.sort_order ASC, e.id ASC
                """,
                (session["id"], coach_id, member_id)
            )
            session["exercises"] = [dict(row) for row in c.fetchall()]
            sessions.append(session)
        return sessions
    finally:
        conn.close()


def get_exercise_library_names():
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("SELECT name FROM exercise_library ORDER BY id ASC")
        return [row[0] for row in c.fetchall() if row[0]]
    finally:
        conn.close()
