import { createClient } from '@supabase/supabase-js';

const supabaseUrl     = import.meta.env.VITE_SUPABASE_URL     || 'https://placeholder.supabase.co';
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY
  || import.meta.env.VITE_SUPABASE_KEY
  || 'placeholder-key';

export const supabase = createClient(supabaseUrl, supabaseAnonKey, {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    // PKCE: email confirm / reset links carry a one-time code, not the session tokens.
    // A code is useless without the verifier stored on the device that asked for the
    // email, so another app that grabs the astraphe:// link (custom schemes aren't
    // exclusive on iOS) gets nothing. The implicit flow put access + refresh tokens
    // in the link itself. Note: the link must be opened on the same device/app.
    flowType: 'pkce',
  },
});
