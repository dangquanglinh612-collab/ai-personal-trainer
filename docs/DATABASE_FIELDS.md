# SQLite 数据表与字段说明

当前本地应用使用 `ai_coach_os.db`。SQLite 不支持 PostgreSQL 那样的 `COMMENT ON TABLE/COLUMN`，所以字段说明保存在这里；不会修改业务数据。`sqlite_sequence` 是 SQLite 自身维护的自增计数表，不属于业务表。

以下按当前数据库的实际字段列出。时间字段在 SQLite 中以文本保存；字段中可填写自由文本的数值不要假定已有统一单位。

## coaches — 本地教练登录账号

| 字段 | 说明 |
| --- | --- |
| id | 本地教练记录主键。 |
| username | 登录用户名，也是其他本地表中的 `coach_id`。 |
| password | 登录密码，当前为明文；正式上线不迁移此值。 |
| nickname | 教练显示名称。 |
| created_at | 账号创建时间。 |

## members — 会员资料与课时

| 字段 | 说明 |
| --- | --- |
| id | 会员主键。 |
| coach_id | 所属教练的本地用户名。 |
| name | 会员姓名。 |
| created_at | 会员创建时间。 |
| remaining_lessons | 剩余课时。 |
| goal | 训练目标。 |
| last_training_date | 最近一次训练日期。 |
| ai_reminder | 会员页显示的提醒文本。 |
| avatar_emoji | 头像表情符号；当前数据库保留的历史字段，现行 `init_db` 不创建。 |
| phone | 联系电话。 |
| note | 会员备注。 |

## exercise_library — 共享动作库

| 字段 | 说明 |
| --- | --- |
| id | 动作主键。 |
| name | 动作标准名称。 |
| category | 动作分类。 |
| equipment | 所需器械。 |
| aliases | 动作别名文本。 |
| created_at | 动作创建时间。 |

## body_measurements — 身体数据记录

| 字段 | 说明 |
| --- | --- |
| id | 身体数据记录主键。 |
| coach_id | 所属教练的本地用户名。 |
| member_id | 所属会员 ID。 |
| record_date | 测量日期。 |
| height | 身高原始输入文本，单位由录入者注明。 |
| weight | 体重原始输入文本，单位由录入者注明。 |
| body_fat | 体脂原始输入文本。 |
| waist | 腰围原始输入文本，单位由录入者注明。 |
| hip | 臀围原始输入文本，单位由录入者注明。 |
| note | 本次测量备注。 |
| created_at | 记录创建时间。 |

## training_sessions — 训练课记录

| 字段 | 说明 |
| --- | --- |
| id | 训练课主键。 |
| coach_id | 所属教练的本地用户名。 |
| member_id | 受训会员 ID。 |
| training_date | 训练日期。 |
| member_feedback | 会员本次训练反馈。 |
| coach_note | 教练本次训练备注。 |
| raw_paste_text | 智能粘贴的原始训练文本。 |
| created_at | 训练课记录创建时间。 |

## training_session_exercises — 训练课动作明细

| 字段 | 说明 |
| --- | --- |
| id | 训练动作明细主键。 |
| session_id | 所属训练课 ID。 |
| exercise_id | 可选的动作库 ID。 |
| exercise_name | 保存时的动作名称快照。 |
| weight | 使用重量原始输入文本。 |
| sets | 组数原始输入文本。 |
| reps | 次数原始输入文本。 |
| rpe | 主观用力程度 RPE 原始输入文本。 |
| note | 该动作备注。 |
| sort_order | 动作在训练课中的显示顺序。 |

## training_session_photos — 训练照片

| 字段 | 说明 |
| --- | --- |
| id | 照片记录主键。 |
| coach_id | 所属教练的本地用户名。 |
| member_id | 照片所属会员 ID。 |
| session_id | 照片所属训练课 ID；历史记录可能为空。 |
| file_path | 本地照片相对路径。 |
| original_filename | 上传时的原始文件名。 |
| caption | 照片说明。 |
| created_at | 照片记录创建时间。 |

## ai_analysis_reports — AI 分析报告

| 字段 | 说明 |
| --- | --- |
| id | 分析报告主键。 |
| coach_id | 所属教练的本地用户名。 |
| member_id | 分析对象会员 ID。 |
| report_date | 报告日期。 |
| report_markdown | 报告 Markdown 正文。 |
| input_summary | 生成报告时的输入摘要。 |
| created_at | 报告创建时间。 |

## training_plans — 训练计划

| 字段 | 说明 |
| --- | --- |
| id | 训练计划主键。 |
| coach_id | 所属教练的本地用户名。 |
| member_id | 计划所属会员 ID。 |
| plan_date | 计划日期。 |
| status | 计划状态，现有数据按原值保存。 |
| source_analysis_report_id | 可选的来源 AI 分析报告 ID。 |
| plan_goal | 本计划的训练目标。 |
| coach_note | 教练对计划的备注。 |
| raw_ai_plan | AI 输出的原始计划文本。 |
| created_at | 计划创建时间。 |
| updated_at | 计划最后更新时间。 |

## training_plan_exercises — 计划动作明细

| 字段 | 说明 |
| --- | --- |
| id | 计划动作明细主键。 |
| plan_id | 所属训练计划 ID。 |
| exercise_id | 可选的动作库 ID。 |
| exercise_name | 计划中的动作名称快照。 |
| target_weight | 目标重量原始输入文本。 |
| sets | 目标组数原始输入文本。 |
| reps | 目标次数原始输入文本。 |
| target_rpe | 目标主观用力程度 RPE 原始输入文本。 |
| note | 该计划动作备注。 |
| sort_order | 动作在计划中的显示顺序。 |

## appointments — 预约课表

| 字段 | 说明 |
| --- | --- |
| id | 预约主键。 |
| coach_id | 所属教练的本地用户名。 |
| member_id | 预约会员 ID。 |
| appointment_date | 预约日期。 |
| start_time | 预约开始时间。 |
| end_time | 预约结束时间。 |
| status | 预约状态：`scheduled`、`completed` 或 `cancelled`。 |
| note | 预约备注。 |
| training_plan_id | 可选的关联训练计划 ID。 |
| training_session_id | 可选的关联训练课 ID。 |
| created_at | 预约创建时间。 |
| updated_at | 预约最后更新时间。 |

## lesson_plans — 旧版课程安排

仅保留历史/演示数据，当前预约页面使用 `appointments`，迁移脚本不迁移本表。

| 字段 | 说明 |
| --- | --- |
| id | 旧课程安排主键。 |
| coach_id | 所属教练的本地用户名。 |
| member_id | 对应会员 ID。 |
| plan_date | 安排日期。 |
| plan_time | 安排时间文本。 |
| status | 旧安排状态。 |
| content | 安排内容。 |
| created_at | 记录创建时间。 |

## training_logs — 旧版训练日志

当前训练页面使用 `training_sessions`，迁移脚本不迁移本表。

| 字段 | 说明 |
| --- | --- |
| id | 旧训练日志主键。 |
| coach_id | 所属教练的本地用户名。 |
| member_id | 对应会员 ID。 |
| content | 旧日志内容。 |
| created_at | 记录创建时间。 |
