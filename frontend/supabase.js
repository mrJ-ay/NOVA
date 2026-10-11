import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL = "https://rmryhapczicyytehgsmk.supabase.co";
const SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJtcnloYXBjemljeXl0ZWhnc21rIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTE0Njg4NjQsImV4cCI6MjEwNzA0NDg2NH0.qudDlxzt37swRO__txO1JUyr609TZGW0ol9rbANxW_0";

export const supabase = createClient(SUPABASE_URL, SUPABASE_KEY);
