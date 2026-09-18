"""Coach-scoped appointment persistence and conflict validation."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime

from .database import get_conn


ALLOWED_APPOINTMENT_STATUSES = {"scheduled", "completed", "cancelled"}


def _normalize_date(value) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError("预约日期必须使用 YYYY-MM-DD 格式。") from exc


def _normalize_time(value) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    text = str(value or "").strip()
    try:
        return datetime.strptime(text, "%H:%M").strftime("%H:%M")
    except ValueError as exc:
        raise ValueError("预约时间必须使用 HH:MM 格式。") from exc


def _normalize_time_range(start_time, end_time) -> tuple[str, str]:
    normalized_start = _normalize_time(start_time)
    normalized_end = _normalize_time(end_time)
    if normalized_start >= normalized_end:
        raise ValueError("开始时间必须早于结束时间。")
    return normalized_start, normalized_end


def get_member_options_for_coach(coach_id):
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, name, goal, remaining_lessons
            FROM members
            WHERE coach_id = ?
            ORDER BY name COLLATE NOCASE ASC, id ASC
            """,
            (coach_id,),
        )
        return cursor.fetchall()
    finally:
        conn.close()


def get_appointments_for_date(coach_id, appointment_date):
    normalized_date = _normalize_date(appointment_date)
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                a.id,
                a.coach_id,
                a.member_id,
                a.appointment_date,
                a.start_time,
                a.end_time,
                a.status,
                a.note,
                a.training_plan_id,
                a.training_session_id,
                a.created_at,
                a.updated_at,
                m.name AS member_name,
                m.goal AS training_goal,
                m.remaining_lessons
            FROM appointments a
            INNER JOIN members m
                ON m.id = a.member_id
               AND m.coach_id = a.coach_id
            WHERE a.coach_id = ? AND a.appointment_date = ?
            ORDER BY a.start_time ASC, a.id ASC
            """,
            (coach_id, normalized_date),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_appointment_by_id(coach_id, appointment_id):
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                a.id,
                a.coach_id,
                a.member_id,
                a.appointment_date,
                a.start_time,
                a.end_time,
                a.status,
                a.note,
                a.training_plan_id,
                a.training_session_id,
                a.created_at,
                a.updated_at,
                m.name AS member_name,
                m.goal AS training_goal,
                m.remaining_lessons
            FROM appointments a
            INNER JOIN members m
                ON m.id = a.member_id
               AND m.coach_id = a.coach_id
            WHERE a.coach_id = ? AND a.id = ?
            LIMIT 1
            """,
            (coach_id, appointment_id),
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def check_appointment_conflict(
    coach_id,
    appointment_date,
    start_time,
    end_time,
    exclude_appointment_id=None,
):
    normalized_date = _normalize_date(appointment_date)
    normalized_start, normalized_end = _normalize_time_range(
        start_time, end_time
    )
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        return _check_appointment_conflict_with_cursor(
            cursor,
            coach_id,
            normalized_date,
            normalized_start,
            normalized_end,
            exclude_appointment_id,
        )
    finally:
        conn.close()


def _check_appointment_conflict_with_cursor(
    cursor,
    coach_id,
    appointment_date,
    start_time,
    end_time,
    exclude_appointment_id=None,
):
    query = """
        SELECT
            a.id,
            a.coach_id,
            a.member_id,
            a.appointment_date,
            a.start_time,
            a.end_time,
            a.status,
            a.note,
            a.training_plan_id,
            a.training_session_id,
            m.name AS member_name,
            m.goal AS training_goal,
            m.remaining_lessons
        FROM appointments a
        INNER JOIN members m
            ON m.id = a.member_id
           AND m.coach_id = a.coach_id
        WHERE a.coach_id = ?
          AND a.appointment_date = ?
          AND a.status != 'cancelled'
          AND a.start_time < ?
          AND a.end_time > ?
    """
    params = [coach_id, appointment_date, end_time, start_time]
    if exclude_appointment_id is not None:
        query += " AND a.id != ?"
        params.append(exclude_appointment_id)
    query += " ORDER BY a.start_time ASC, a.id ASC LIMIT 1"
    cursor.execute(query, params)
    row = cursor.fetchone()
    return {
        "has_conflict": row is not None,
        "appointment": dict(row) if row else None,
    }


def _member_belongs_to_coach(cursor, coach_id, member_id) -> bool:
    cursor.execute(
        "SELECT 1 FROM members WHERE coach_id = ? AND id = ? LIMIT 1",
        (coach_id, member_id),
    )
    return cursor.fetchone() is not None


def create_appointment(
    coach_id,
    member_id,
    appointment_date,
    start_time,
    end_time,
    note="",
):
    normalized_date = _normalize_date(appointment_date)
    normalized_start, normalized_end = _normalize_time_range(
        start_time, end_time
    )

    conn = get_conn()
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.cursor()
        if not _member_belongs_to_coach(cursor, coach_id, member_id):
            raise ValueError("会员不存在或不属于当前教练。")
        conflict = _check_appointment_conflict_with_cursor(
            cursor,
            coach_id,
            normalized_date,
            normalized_start,
            normalized_end,
        )
        if conflict["has_conflict"]:
            conn.rollback()
            return conflict
        now = datetime.now().isoformat(timespec="seconds")
        cursor.execute(
            """
            INSERT INTO appointments (
                coach_id, member_id, appointment_date, start_time,
                end_time, status, note, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 'scheduled', ?, ?, ?)
            """,
            (
                coach_id,
                member_id,
                normalized_date,
                normalized_start,
                normalized_end,
                str(note or "").strip(),
                now,
                now,
            ),
        )
        appointment_id = cursor.lastrowid
        conn.commit()
        return appointment_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_appointment(
    coach_id,
    appointment_id,
    member_id,
    appointment_date,
    start_time,
    end_time,
    note="",
):
    normalized_date = _normalize_date(appointment_date)
    normalized_start, normalized_end = _normalize_time_range(
        start_time, end_time
    )

    conn = get_conn()
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM appointments WHERE coach_id = ? AND id = ? LIMIT 1",
            (coach_id, appointment_id),
        )
        if cursor.fetchone() is None:
            raise ValueError("预约不存在或不属于当前教练。")
        if not _member_belongs_to_coach(cursor, coach_id, member_id):
            raise ValueError("会员不存在或不属于当前教练。")
        conflict = _check_appointment_conflict_with_cursor(
            cursor,
            coach_id,
            normalized_date,
            normalized_start,
            normalized_end,
            exclude_appointment_id=appointment_id,
        )
        if conflict["has_conflict"]:
            conn.rollback()
            return conflict
        cursor.execute(
            """
            UPDATE appointments
            SET member_id = ?, appointment_date = ?, start_time = ?,
                end_time = ?, note = ?, updated_at = ?
            WHERE coach_id = ? AND id = ?
            """,
            (
                member_id,
                normalized_date,
                normalized_start,
                normalized_end,
                str(note or "").strip(),
                datetime.now().isoformat(timespec="seconds"),
                coach_id,
                appointment_id,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("预约更新失败。")
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_appointment_status(coach_id, appointment_id, status):
    normalized_status = str(status or "").strip()
    if normalized_status not in ALLOWED_APPOINTMENT_STATUSES:
        raise ValueError("不支持的预约状态。")

    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE appointments
            SET status = ?, updated_at = ?
            WHERE coach_id = ? AND id = ?
            """,
            (
                normalized_status,
                datetime.now().isoformat(timespec="seconds"),
                coach_id,
                appointment_id,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("预约不存在或不属于当前教练。")
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_next_appointment_for_member(coach_id, member_id):
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, coach_id, member_id, appointment_date, start_time,
                   end_time, status, note, training_plan_id,
                   training_session_id, created_at, updated_at
            FROM appointments
            WHERE coach_id = ?
              AND member_id = ?
              AND status = 'scheduled'
              AND appointment_date >= ?
            ORDER BY appointment_date ASC, start_time ASC, id ASC
            LIMIT 1
            """,
            (coach_id, member_id, date.today().isoformat()),
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_upcoming_appointments_for_coach(coach_id, limit=10):
    try:
        safe_limit = max(1, min(100, int(limit)))
    except (TypeError, ValueError):
        safe_limit = 10

    conn = get_conn()
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                a.id,
                a.coach_id,
                a.member_id,
                a.appointment_date,
                a.start_time,
                a.end_time,
                a.status,
                a.note,
                a.training_plan_id,
                a.training_session_id,
                m.name AS member_name,
                m.goal AS training_goal,
                m.remaining_lessons
            FROM appointments a
            INNER JOIN members m
                ON m.id = a.member_id
               AND m.coach_id = a.coach_id
            WHERE a.coach_id = ?
              AND a.status = 'scheduled'
              AND a.appointment_date >= ?
            ORDER BY a.appointment_date ASC, a.start_time ASC, a.id ASC
            LIMIT ?
            """,
            (coach_id, date.today().isoformat(), safe_limit),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()
