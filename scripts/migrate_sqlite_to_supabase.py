"""Offline by default. Explicit stage-C gates are required before any remote I/O."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from datetime import date, datetime, time, timezone, timedelta
from uuid import UUID, uuid5, NAMESPACE_URL

ROOT = Path(__file__).resolve().parents[1]
TABLES = (
    "exercise_library", "members", "body_measurements", "training_sessions",
    "training_session_exercises", "ai_analysis_reports", "training_plans",
    "training_plan_exercises", "appointments", "training_session_photos",
)
LEGACY = ("lesson_plans", "training_logs")
DATES = {"last_training_date", "record_date", "training_date", "report_date", "plan_date", "appointment_date"}
TIMESTAMPS = {"created_at", "updated_at"}
COLUMNS = {
    "exercise_library": "id name category equipment aliases created_at",
    "members": "id coach_id name created_at remaining_lessons goal last_training_date ai_reminder avatar_emoji phone note",
    "body_measurements": "id coach_id member_id record_date height weight body_fat waist hip note created_at",
    "training_sessions": "id coach_id member_id training_date member_feedback coach_note raw_paste_text created_at",
    "training_session_exercises": "id session_id exercise_id exercise_name weight sets reps rpe note sort_order",
    "ai_analysis_reports": "id coach_id member_id report_date report_markdown input_summary created_at",
    "training_plans": "id coach_id member_id plan_date status source_analysis_report_id plan_goal coach_note raw_ai_plan created_at updated_at",
    "training_plan_exercises": "id plan_id exercise_id exercise_name target_weight sets reps target_rpe note sort_order",
    "appointments": "id coach_id member_id appointment_date start_time end_time status note training_plan_id training_session_id created_at updated_at",
    "training_session_photos": "id coach_id member_id session_id file_path original_filename caption created_at",
}


def normalize_value(field, value):
    if field in DATES:
        return date.fromisoformat(value).isoformat() if value else None
    if field in ("start_time", "end_time"):
        return time.fromisoformat(value).isoformat()
    if field in TIMESTAMPS:
        if not value:
            return None
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            # Audited local timestamps were written with datetime.now(), Asia/Shanghai.
            timestamp = timestamp.replace(tzinfo=timezone(timedelta(hours=8)))
        return timestamp.astimezone(timezone.utc).isoformat()
    return value


def photo_file(root, stored):
    if not stored:
        raise ValueError("empty photo path")
    root = root.resolve()
    path = Path(stored)
    path = (path if path.is_absolute() else root / path).resolve()
    allowed = (root / "uploads" / "training_photos").resolve()
    if not path.is_relative_to(allowed) or not path.is_file():
        raise ValueError("photo missing or outside uploads/training_photos")
    if path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
        raise ValueError("unsupported photo extension")
    return path


def build_plan(db_path, mapping, project_root=ROOT):
    """Read-only snapshot + FK/ownership/type/file validation. No client creation."""
    db_path = Path(db_path).resolve()
    if not db_path.is_file():
        raise ValueError("SQLite 文件不存在")
    errors, warnings, rows, counts, files = [], [], {}, {}, {}
    mapping = dict(mapping)
    for old, new in mapping.items():
        try:
            mapping[old] = str(UUID(new))
        except (ValueError, TypeError, AttributeError):
            errors.append(f"coach mapping 无效：{old}")
    if len(set(mapping.values())) != len(mapping):
        errors.append("不同旧教练不能映射到同一 Auth UUID")
    conn = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            errors.append("SQLite integrity_check 未通过")
        present = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        unknown = present - set(TABLES) - set(LEGACY) - {"coaches", "sqlite_sequence"}
        if unknown:
            errors.append("存在未审计表：" + ",".join(sorted(unknown)))
        for table in TABLES + LEGACY:
            if table not in present:
                errors.append(f"缺少表：{table}")
                rows[table] = []
                continue
            counts[table] = conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            if table in LEGACY:
                continue
            columns = {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}
            unexpected = columns - set(COLUMNS[table].split())
            if unexpected:
                errors.append(f"{table} 含未映射字段：{','.join(sorted(unexpected))}")
            missing = set(COLUMNS[table].split()) - columns - {"avatar_emoji"}
            if missing:
                errors.append(f"{table} 缺少预期字段：{','.join(sorted(missing))}")
                rows[table] = []
                continue
            rows[table] = [dict(row) for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY id')]
        coaches = [dict(row) for row in conn.execute("SELECT username, nickname FROM coaches")]
        for coach in coaches:
            if coach["username"] not in mapping:
                errors.append(f"缺少 coach mapping：{coach['username']}")
        conn.rollback()
    finally:
        conn.close()
    lookup = {t: {row["id"]: row for row in rows.get(t, [])} for t in TABLES}
    for table in TABLES:
        for row in rows[table]:
            label = f"{table}#{row['id']}"
            if row.get("coach_id") is not None and row["coach_id"] not in mapping:
                errors.append(f"{label} 缺少 coach mapping")
            links = []
            if "member_id" in row:
                links.append(("member_id", "members"))
            if "exercise_id" in row:
                links.append(("exercise_id", "exercise_library"))
            if "session_id" in row:
                links.append(("session_id", "training_sessions"))
            if "plan_id" in row:
                links.append(("plan_id", "training_plans"))
            for field, parent in (("source_analysis_report_id", "ai_analysis_reports"), ("training_plan_id", "training_plans"), ("training_session_id", "training_sessions")):
                if field in row:
                    links.append((field, parent))
            for field, parent in links:
                if row[field] is None:
                    if field in ("member_id", "session_id", "plan_id"):
                        errors.append(f"{label} 缺少 {field}")
                    continue
                target = lookup[parent].get(row[field])
                if not target:
                    errors.append(f"{label} 孤儿 FK：{field}")
                elif "coach_id" in row and target.get("coach_id", row["coach_id"]) != row["coach_id"]:
                    errors.append(f"{label} 跨教练 FK：{field}")
                elif "member_id" in row and "member_id" in target and row["member_id"] != target["member_id"]:
                    errors.append(f"{label} 跨会员 FK：{field}")
            if table == "members" and (row.get("remaining_lessons") is not None and row["remaining_lessons"] < 0):
                errors.append(f"{label} 负课时")
            allowed_status = {"appointments": {"scheduled", "completed", "cancelled"}, "training_plans": {"draft", "confirmed", "used"}}.get(table)
            if allowed_status and row.get("status") not in allowed_status:
                errors.append(f"{label} 无效 status")
            for field, value in list(row.items()):
                try:
                    row[field] = normalize_value(field, value)
                    if field in DATES - {"last_training_date"} and row[field] is None:
                        raise ValueError("required date")
                except (ValueError, TypeError, AttributeError):
                    errors.append(f"{label} 日期/时间无效：{field}")
            if table == "training_session_photos":
                try:
                    path = photo_file(Path(project_root), row["file_path"])
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                    object_id = uuid5(NAMESPACE_URL, f"ai-coach/{mapping.get(row['coach_id'])}/{row['id']}/{digest}")
                    row["object_path"] = f"{mapping.get(row['coach_id'])}/{row['member_id']}/{row['session_id']}/{object_id}{path.suffix.lower()}"
                    row["bucket_name"] = "training-photos"
                    files[row["id"]] = {"path": str(path), "sha256": digest}
                    del row["file_path"]
                except (ValueError, OSError):
                    errors.append(f"{label} 照片缺失、路径越界或格式不支持")
    appointments = rows["appointments"]
    for i, row in enumerate(appointments):
        if not isinstance(row.get("start_time"), str) or not isinstance(row.get("end_time"), str):
            continue
        if row["start_time"] >= row["end_time"]:
            errors.append(f"appointments#{row['id']} 时间范围无效")
        for other in appointments[:i]:
            if not isinstance(other.get("start_time"), str) or not isinstance(other.get("end_time"), str):
                continue
            if row["status"] != "cancelled" and other["status"] != "cancelled" and row["coach_id"] == other["coach_id"] and row["appointment_date"] == other["appointment_date"] and row["start_time"] < other["end_time"] and row["end_time"] > other["start_time"]:
                errors.append(f"appointments#{row['id']} 与 #{other['id']} 冲突")
    for table in TABLES:
        for row in rows[table]:
            if "coach_id" in row:
                row["coach_id"] = mapping.get(row["coach_id"])
    rows["profiles"] = [{"id": mapping[c["username"]], "display_name": c["nickname"] or c["username"]}
                        for c in coaches if c["username"] in mapping]
    warnings.append("legacy/not migrated: lesson_plans, training_logs; coaches.password 不导出")
    return {"rows": rows, "files": files, "counts": counts, "errors": list(dict.fromkeys(errors)), "warnings": warnings}


def _same_row(expected, actual):
    return all(normalize_value(k, actual.get(k)) == normalize_value(k, v) for k, v in expected.items())


def execute_plan(plan, client):
    """Insert-only resumable migration; conflicts abort before any writes."""
    if plan["errors"]:
        raise ValueError("dry-run 校验未通过")
    order = ("profiles",) + TABLES
    existing = {}
    for profile in plan["rows"]["profiles"]:
        if client.auth.admin.get_user_by_id(profile["id"]).user.id != profile["id"]:
            raise ValueError("Auth mapping 未验证")
    bucket = client.storage.get_bucket("training-photos")
    if (bucket.get("public") if isinstance(bucket, dict) else bucket.public) is not False:
        raise ValueError("Storage bucket 必须 private")
    for table in order:
        expected = {r["id"]: r for r in plan["rows"][table]}
        actual, offset = {}, 0
        while True:
            batch = client.table(table).select("*").order("id").range(offset, offset + 499).execute().data
            actual.update({r["id"]: r for r in batch})
            if len(batch) < 500:
                break
            offset += 500
        if set(actual) - set(expected):
            raise ValueError(f"{table} 存在非本次迁移数据，停止，禁止覆盖")
        for row_id, row in actual.items():
            if not _same_row(expected[row_id], row):
                raise ValueError(f"{table}#{row_id} 与源数据不一致，停止，禁止覆盖")
        existing[table] = actual
    result = {"inserted": {}, "remote_counts": {}, "photos_verified": 0, "photo_failures": [], "failed_rows": []}
    for table in order:
        result["inserted"][table] = 0
        for row in plan["rows"][table]:
            if table == "training_session_photos":
                try:
                    file = plan["files"][row["id"]]
                    content = Path(file["path"]).read_bytes()
                    if hashlib.sha256(content).hexdigest() != file["sha256"]:
                        raise ValueError("source changed")
                    storage = client.storage.from_("training-photos")
                    folder, filename = row["object_path"].rsplit("/", 1)
                    found = storage.list(folder, {"search": filename, "limit": 100})
                    if not any(item["name"] == filename for item in found):
                        storage.upload(row["object_path"], content, file_options={"upsert": "false", "content-type": "image/png" if filename.endswith(".png") else "image/jpeg"})
                    if hashlib.sha256(storage.download(row["object_path"])).hexdigest() != file["sha256"]:
                        raise ValueError("storage differs")
                    result["photos_verified"] += 1
                except Exception:
                    result["photo_failures"].append(row["id"])
                    continue
            if row["id"] not in existing[table]:
                try:
                    client.table(table).insert(row).execute()
                except Exception:
                    result["failed_rows"].append({"table": table, "id": row["id"]})
                    result["success"] = False
                    return result
                result["inserted"][table] += 1
        result["remote_counts"][table] = client.table(table).select("id", count="exact", head=True).execute().count
    client.rpc("realign_migration_sequences").execute()
    result["success"] = not result["photo_failures"] and all(result["remote_counts"][t] == len(plan["rows"][t]) for t in order)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", default=str(ROOT / "ai_coach_os.db"))
    parser.add_argument("--project-root", default=str(ROOT))
    parser.add_argument("--coach-map")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-project", help="Exact Supabase project ref, required for execute")
    parser.add_argument("--backups-confirmed", action="store_true")
    args = parser.parse_args(argv)
    try:
        mapping = json.loads(Path(args.coach_map).read_text(encoding="utf-8")) if args.coach_map else {}
        plan = build_plan(args.sqlite, mapping, Path(args.project_root))
        # Report never includes member data, tokens, or passwords.
        print(json.dumps({k: plan[k] for k in ("counts", "errors", "warnings")}, ensure_ascii=False, indent=2))
        if plan["errors"]:
            return 2
        if not args.execute:
            print("DRY RUN ONLY: no Supabase connection or writes")
            return 0
        if not args.backups_confirmed or not args.confirm_project:
            raise ValueError("execute 需要确认 SQLite/uploads 已备份，并指定 --confirm-project")
        url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        if url != f"https://{args.confirm_project}.supabase.co":
            raise ValueError("项目 URL 与显式确认不匹配")
        secret = os.environ.get("SUPABASE_SECRET_KEY", "")
        if not secret.startswith("sb_secret_"):
            raise ValueError("迁移 Secret Key 只能从本地环境变量配置")
        from supabase import create_client, ClientOptions
        client = create_client(url, secret, options=ClientOptions(persist_session=False, auto_refresh_token=False))
        result = execute_plan(plan, client)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["success"] else 2
    except Exception as exc:
        # Do not print SDK exceptions: they may embed request headers or personal data.
        print(f"迁移未完成（{type(exc).__name__}）。保留本地数据；核对 dry-run、配置和远程只读状态后再续跑。", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
