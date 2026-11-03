<script lang="ts">
  import { onMount } from 'svelte';
  import type { Session } from '@supabase/supabase-js';
  import { supabase } from '$lib/supabase';
  import { completeAuthSession } from '$lib/utils/completeAuthSession';

  let sessionOk = $state<boolean | null>(null);

  async function handleConfirmedSession(session: Session) {
    // A session that arrives after the timeout still wins (slow token exchange).
    if (sessionOk === true) return;
    sessionOk = true;
    await completeAuthSession(session);
  }

  onMount(() => {
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((event, session) => {
      if (event === 'SIGNED_IN' && session && sessionOk !== true) {
        void handleConfirmedSession(session);
      }
    });

    void (async () => {
      const { data } = await supabase.auth.getSession();
      if (data.session && sessionOk !== true) {
        await handleConfirmedSession(data.session);
      }
    })();

    const errorTimer = setTimeout(() => {
      if (sessionOk === null) {
        sessionOk = false;
      }
    }, 10000);

    return () => {
      subscription.unsubscribe();
      clearTimeout(errorTimer);
    };
  });
</script>

<div class="min-h-full flex flex-col p-6 items-center justify-center relative">
  <div class="absolute -top-[100px] -right-[100px] w-[300px] h-[300px] bg-teal rounded-full blur-[120px] opacity-20 pointer-events-none"></div>

  <div class="w-full max-w-sm z-10">
    {#if sessionOk === false}
      <div class="p-3 bg-red-dim border-l-2 border-red rounded-lg text-xs text-text0 leading-relaxed text-center">
        <p class="mb-4">Link expired or invalid</p>
        <a href="/auth/signup" class="text-teal hover:underline font-mono text-[10px] uppercase tracking-widest">
          Back to Sign Up
        </a>
      </div>
    {:else}
      <div class="text-center">
        <div class="w-16 h-16 rounded-2xl bg-blue-dim border border-blue/30 flex items-center justify-center mx-auto mb-6">
          <span class="text-3xl font-bold text-text0">A</span>
        </div>
        <p class="text-text2 text-sm animate-pulse">Confirming your account…</p>
      </div>
    {/if}
  </div>
</div>
