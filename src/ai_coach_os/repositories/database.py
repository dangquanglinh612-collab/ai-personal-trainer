"""SQLite schema bootstrap and connection helpers."""

import sqlite3
from datetime import date, datetime, timedelta

from ai_coach_os.config import DEFAULT_DB_NAME, PROJECT_ROOT as DEFAULT_PROJECT_ROOT

DB_NAME = DEFAULT_DB_NAME
PROJECT_ROOT = DEFAULT_PROJECT_ROOT

def get_conn():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def column_exists(cursor, table_name, column_name):
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    return column_name in columns


def add_column_if_not_exists(cursor, table_name, column_name, column_sql):
    if not column_exists(cursor, table_name, column_name):
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")


def init_db():
    conn = get_conn()
    try:
        _init_db_with_connection(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _init_db_with_connection(conn):
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS coaches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        nickname TEXT,
        created_at TEXT
    )
    """)

    add_column_if_not_exists(c, "coaches", "nickname", "nickname TEXT DEFAULT ''")

    c.execute("""
    CREATE TABLE IF NOT EXISTS members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        coach_id TEXT NOT NULL,
        name TEXT NOT NULL,
        created_at TEXT
    )
    """)

    add_column_if_not_exists(c, "members", "remaining_lessons", "remaining_lessons INTEGER DEFAULT 10")
    add_column_if_not_exists(c, "members", "goal", "goal TEXT DEFAULT ''")
    add_column_if_not_exists(c, "members", "last_training_date", "last_training_date TEXT DEFAULT ''")
    add_column_if_not_exists(c, "members", "ai_reminder", "ai_reminder TEXT DEFAULT ''")
    add_column_if_not_exists(c, "members", "phone", "phone TEXT DEFAULT ''")
    add_column_if_not_exists(c, "members", "note", "note TEXT DEFAULT ''")

    c.execute("""
    CREATE TABLE IF NOT EXISTS training_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        coach_id TEXT NOT NULL,
        member_id INTEGER NOT NULL,
        content TEXT,
        created_at TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS lesson_plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        coach_id TEXT NOT NULL,
        member_id INTEGER NOT NULL,
        plan_date TEXT NOT NULL,
        plan_time TEXT,
        status TEXT DEFAULT 'planned',
        content TEXT,
        created_at TEXT
    )
    """)

    add_column_if_not_exists(c, "lesson_plans", "plan_time", "plan_time TEXT")
    add_column_if_not_exists(c, "lesson_plans", "status", "status TEXT DEFAULT 'planned'")
    add_column_if_not_exists(c, "lesson_plans", "content", "content TEXT")

    c.execute("""
    CREATE TABLE IF NOT EXISTS exercise_library (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        category TEXT DEFAULT '',
        equipment TEXT DEFAULT '',
        aliases TEXT DEFAULT '',
        created_at TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS training_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        coach_id TEXT NOT NULL,
        member_id INTEGER NOT NULL,
        training_date TEXT NOT NULL,
        member_feedback TEXT DEFAULT '',
        coach_note TEXT DEFAULT '',
        raw_paste_text TEXT DEFAULT '',
        created_at TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS body_measurements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        coach_id TEXT NOT NULL,
        member_id INTEGER NOT NULL,
        record_date TEXT NOT NULL,
        height TEXT DEFAULT '',
        weight TEXT DEFAULT '',
        body_fat TEXT DEFAULT '',
        waist TEXT DEFAULT '',
        hip TEXT DEFAULT '',
        note TEXT DEFAULT '',
        created_at TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS training_session_photos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        coach_id TEXT NOT NULL,
        member_id INTEGER NOT NULL,
        session_id INTEGER,
        file_path TEXT NOT NULL,
        original_filename TEXT DEFAULT '',
        caption TEXT DEFAULT '',
        created_at TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS training_session_exercises (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        exercise_id INTEGER,
        exercise_name TEXT NOT NULL,
        weight TEXT DEFAULT '',
        sets TEXT DEFAULT '',
        reps TEXT DEFAULT '',
        rpe TEXT DEFAULT '',
        note TEXT DEFAULT '',
        sort_order INTEGER DEFAULT 0
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS ai_analysis_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        coach_id TEXT NOT NULL,
        member_id INTEGER NOT NULL,
        report_date TEXT NOT NULL,
        report_markdown TEXT NOT NULL,
        input_summary TEXT DEFAULT '',
        created_at TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS training_plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        coach_id TEXT NOT NULL,
        member_id INTEGER NOT NULL,
        plan_date TEXT NOT NULL,
        status TEXT DEFAULT 'confirmed',
        source_analysis_report_id INTEGER,
        plan_goal TEXT DEFAULT '',
        coach_note TEXT DEFAULT '',
        raw_ai_plan TEXT DEFAULT '',
        created_at TEXT,
        updated_at TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS training_plan_exercises (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        plan_id INTEGER NOT NULL,
        exercise_id INTEGER,
        exercise_name TEXT NOT NULL,
        target_weight TEXT DEFAULT '',
        sets TEXT DEFAULT '',
        reps TEXT DEFAULT '',
        target_rpe TEXT DEFAULT '',
        note TEXT DEFAULT '',
        sort_order INTEGER DEFAULT 0
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS appointments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        coach_id TEXT NOT NULL,
        member_id INTEGER NOT NULL,
        appointment_date TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        status TEXT DEFAULT 'scheduled',
        note TEXT DEFAULT '',
        training_plan_id INTEGER,
        training_session_id INTEGER,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    c.execute("""
    CREATE INDEX IF NOT EXISTS idx_training_sessions_member
    ON training_sessions (coach_id, member_id, training_date)
    """)

    c.execute("""
    CREATE INDEX IF NOT EXISTS idx_training_exercises_session
    ON training_session_exercises (session_id, sort_order)
    """)

    c.execute("""
    CREATE INDEX IF NOT EXISTS idx_ai_analysis_reports_member
    ON ai_analysis_reports (coach_id, member_id, created_at)
    """)

    c.execute("""
    CREATE INDEX IF NOT EXISTS idx_body_measurements_member
    ON body_measurements (coach_id, member_id, record_date, id)
    """)

    c.execute("""
    CREATE INDEX IF NOT EXISTS idx_training_session_photos_session
    ON training_session_photos (coach_id, member_id, session_id, created_at, id)
    """)

    c.execute("""
    CREATE INDEX IF NOT EXISTS idx_training_plans_member
    ON training_plans (coach_id, member_id, plan_date, id)
    """)

    c.execute("""
    CREATE INDEX IF NOT EXISTS idx_training_plan_exercises_plan
    ON training_plan_exercises (plan_id, sort_order, id)
    """)

    c.execute("""
    CREATE INDEX IF NOT EXISTS idx_appointments_coach_date
    ON appointments (coach_id, appointment_date, start_time)
    """)

    seed_default_coaches(c)
    seed_exercise_library(c)

    c.execute("UPDATE members SET goal = '改善体态' WHERE goal = '体态改善'")

    seed_demo_members(c)


def seed_default_coaches(cursor):
    default_coaches = [
        ("wenwen", "123456", "文文教练"),
        ("numb", "123456", "Numb教练"),
    ]

    for username, password, nickname in default_coaches:
        cursor.execute("SELECT id FROM coaches WHERE username = ?", (username,))
        if not cursor.fetchone():
            cursor.execute("""
            INSERT INTO coaches (username, password, nickname, created_at)
            VALUES (?, ?, ?, ?)
            """, (
                username,
                password,
                nickname,
                datetime.now().isoformat(timespec="seconds")
            ))


def seed_exercise_library(cursor):
    cursor.execute("SELECT COUNT(*) FROM exercise_library")
    if cursor.fetchone()[0] > 0:
        return

    default_exercises = [
        "罗马尼亚硬拉", "臀推", "腿举", "坐姿髋外展", "高位下拉",
        "坐姿划船", "哑铃卧推", "杠铃深蹲", "山羊挺身", "平板支撑",
        "哑铃肩推", "绳索下压", "哑铃弯举", "保加利亚分腿蹲", "坐姿腿屈伸",
        "俯身腿弯举", "器械推胸", "器械划船", "跑步机快走", "椭圆机",
    ]
    created_at = datetime.now().isoformat(timespec="seconds")
    cursor.executemany(
        """
        INSERT OR IGNORE INTO exercise_library (name, created_at)
        VALUES (?, ?)
        """,
        [(name, created_at) for name in default_exercises]
    )


def seed_demo_members(cursor):
    today = date.today()

    demo_data = {
        "wenwen": [
            {
                "name": "张三",
                "remaining_lessons": 12,
                "goal": "减脂",
                "last_training_date": str(today - timedelta(days=3)),
                "ai_reminder": "",
                "phone": "未填写",
                "note": "示例备注：减脂目标，注意控制训练节奏。",
                "plan_date": str(today),
                "plan_time": "18:00",
            },
            {
                "name": "李四",
                "remaining_lessons": 2,
                "goal": "增肌",
                "last_training_date": str(today - timedelta(days=6)),
                "ai_reminder": "剩余课时较少，建议关注续课",
                "phone": "未填写",
                "note": "示例备注：增肌目标，训练状态稳定。",
                "plan_date": str(today + timedelta(days=1)),
                "plan_time": "14:00",
            },
            {
                "name": "王五",
                "remaining_lessons": 8,
                "goal": "改善体态",
                "last_training_date": str(today - timedelta(days=15)),
                "ai_reminder": "超过14天未训练",
                "phone": "未填写",
                "note": "示例备注：体态改善，关注肩颈和髋活动度。",
                "plan_date": "",
                "plan_time": "",
            },
        ],
        "numb": [
            {
                "name": "小林",
                "remaining_lessons": 20,
                "goal": "增肌",
                "last_training_date": str(today - timedelta(days=1)),
                "ai_reminder": "",
                "phone": "未填写",
                "note": "",
                "plan_date": str(today),
                "plan_time": "20:00",
            },
            {
                "name": "阿杰",
                "remaining_lessons": 1,
                "goal": "减脂",
                "last_training_date": str(today - timedelta(days=5)),
                "ai_reminder": "剩余1节，建议续课",
                "phone": "未填写",
                "note": "",
                "plan_date": "",
                "plan_time": "",
            },
        ]
    }

    for coach_id, members in demo_data.items():
        cursor.execute("SELECT COUNT(*) FROM members WHERE coach_id = ?", (coach_id,))
        count = cursor.fetchone()[0]

        if count > 0:
            continue

        for member in members:
            cursor.execute("""
            INSERT INTO members (
                coach_id,
                name,
                remaining_lessons,
                goal,
                last_training_date,
                ai_reminder,
                phone,
                note,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                coach_id,
                member["name"],
                member["remaining_lessons"],
                member["goal"],
                member["last_training_date"],
                member["ai_reminder"],
                member["phone"],
                member["note"],
                datetime.now().isoformat(timespec="seconds")
            ))

            member_id = cursor.lastrowid

            if member["plan_date"]:
                cursor.execute("""
                INSERT INTO lesson_plans (
                    coach_id,
                    member_id,
                    plan_date,
                    plan_time,
                    status,
                    content,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    coach_id,
                    member_id,
                    member["plan_date"],
                    member["plan_time"],
                    "planned",
                    "示例预约课程",
                    datetime.now().isoformat(timespec="seconds")
                ))


