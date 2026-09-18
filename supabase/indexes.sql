CREATE INDEX members_coach_name ON public.members(coach_id, name);
CREATE INDEX body_measurements_member_date ON public.body_measurements(coach_id, member_id, record_date DESC);
CREATE INDEX training_sessions_member_date ON public.training_sessions(coach_id, member_id, training_date DESC);
CREATE INDEX ai_analysis_reports_member_date ON public.ai_analysis_reports(coach_id, member_id, report_date DESC);
CREATE INDEX training_plans_member_date ON public.training_plans(coach_id, member_id, plan_date DESC);
CREATE INDEX training_session_exercises_order ON public.training_session_exercises(session_id, sort_order);
CREATE INDEX training_plan_exercises_order ON public.training_plan_exercises(plan_id, sort_order);
CREATE INDEX appointments_coach_date ON public.appointments(coach_id, appointment_date, start_time);
CREATE INDEX training_session_photos_session ON public.training_session_photos(coach_id, member_id, session_id);
