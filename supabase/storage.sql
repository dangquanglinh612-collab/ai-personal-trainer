-- Requires Supabase Storage system schema. Existing bucket must already be private.
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM storage.buckets WHERE id='training-photos' AND public) THEN
    RAISE EXCEPTION 'Existing training-photos bucket is public; stop and review';
  END IF;
END $$;
INSERT INTO storage.buckets(id, name, public) VALUES ('training-photos','training-photos',false) ON CONFLICT(id) DO NOTHING;
CREATE POLICY coach_photos_select ON storage.objects FOR SELECT TO authenticated USING (bucket_id = 'training-photos' AND (storage.foldername(name))[1] = (select auth.uid())::text) ;
CREATE POLICY coach_photos_insert ON storage.objects FOR INSERT TO authenticated  WITH CHECK (bucket_id = 'training-photos' AND (storage.foldername(name))[1] = (select auth.uid())::text);
CREATE POLICY coach_photos_update ON storage.objects FOR UPDATE TO authenticated USING (bucket_id = 'training-photos' AND (storage.foldername(name))[1] = (select auth.uid())::text) WITH CHECK (bucket_id = 'training-photos' AND (storage.foldername(name))[1] = (select auth.uid())::text);
CREATE POLICY coach_photos_delete ON storage.objects FOR DELETE TO authenticated USING (bucket_id = 'training-photos' AND (storage.foldername(name))[1] = (select auth.uid())::text) ;
