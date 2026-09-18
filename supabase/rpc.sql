-- Transactional training API. SECURITY INVOKER: caller JWT/RLS always applies.
CREATE FUNCTION public.save_training_session_transaction(
    p_member_id bigint, p_training_date date, p_member_feedback text,
    p_coach_note text, p_raw_paste_text text, p_exercises jsonb,
    p_session_id bigint DEFAULT NULL
) RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
    v_id bigint; v_deduct boolean := false; v_row jsonb; v_order integer := 0;
BEGIN
    IF auth.uid() IS NULL THEN RAISE EXCEPTION 'Authentication required'; END IF;
    -- Serialize all training saves/updates for this member, including same-day creates.
    PERFORM 1 FROM public.members WHERE id=p_member_id AND coach_id=auth.uid() FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Member not available'; END IF;
    IF jsonb_typeof(p_exercises) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'Exercises must be an array';
    END IF;
    IF p_session_id IS NULL THEN
        SELECT NOT EXISTS(SELECT 1 FROM public.training_sessions
          WHERE member_id=p_member_id AND coach_id=auth.uid() AND training_date=p_training_date)
          INTO v_deduct;
        INSERT INTO public.training_sessions(coach_id,member_id,training_date,member_feedback,coach_note,raw_paste_text)
        VALUES(auth.uid(),p_member_id,p_training_date,p_member_feedback,p_coach_note,p_raw_paste_text)
        RETURNING id INTO v_id;
        UPDATE public.members SET last_training_date=p_training_date,
          remaining_lessons=CASE WHEN v_deduct THEN greatest(0,remaining_lessons-1) ELSE remaining_lessons END
          WHERE id=p_member_id AND coach_id=auth.uid();
    ELSE
        UPDATE public.training_sessions SET training_date=p_training_date,
          member_feedback=p_member_feedback,coach_note=p_coach_note,raw_paste_text=p_raw_paste_text
          WHERE id=p_session_id AND coach_id=auth.uid() AND member_id=p_member_id RETURNING id INTO v_id;
        IF NOT FOUND THEN RAISE EXCEPTION 'Training not available'; END IF;
        DELETE FROM public.training_session_exercises WHERE session_id=v_id;
        -- Existing SQLite update does not change lessons or member.last_training_date.
    END IF;
    FOR v_row IN SELECT value FROM jsonb_array_elements(p_exercises) LOOP
        INSERT INTO public.training_session_exercises(session_id,exercise_id,exercise_name,weight,sets,reps,rpe,note,sort_order)
        VALUES(v_id,(v_row->>'exercise_id')::bigint,v_row->>'exercise_name',
          coalesce(v_row->>'weight',''),coalesce(v_row->>'sets',''),coalesce(v_row->>'reps',''),
          coalesce(v_row->>'rpe',''),coalesce(v_row->>'note',''),v_order);
        v_order := v_order + 1;
    END LOOP;
    RETURN jsonb_build_object('session_id',v_id,'should_deduct_lesson',v_deduct);
END $$;
REVOKE ALL ON FUNCTION public.save_training_session_transaction(bigint,date,text,text,text,jsonb,bigint) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.save_training_session_transaction(bigint,date,text,text,text,jsonb,bigint) TO authenticated;

-- Offline migration only. Never granted to normal users; run with application stopped.
CREATE FUNCTION public.realign_migration_sequences() RETURNS void
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE t text; highest bigint;
BEGIN
    FOREACH t IN ARRAY ARRAY['exercise_library','members','body_measurements','training_sessions',
      'training_session_exercises','ai_analysis_reports','training_plans','training_plan_exercises',
      'appointments','training_session_photos'] LOOP
        EXECUTE format('SELECT max(id) FROM public.%I',t) INTO highest;
        PERFORM pg_catalog.setval(pg_catalog.pg_get_serial_sequence('public.' || t,'id'),
          greatest(coalesce(highest,1),1),highest IS NOT NULL);
    END LOOP;
END $$;
REVOKE ALL ON FUNCTION public.realign_migration_sequences() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.realign_migration_sequences() TO service_role;
