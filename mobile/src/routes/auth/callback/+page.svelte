<script lang="ts">
  import { onMount } from 'svelte';
  import type { Session } from '@supabase/supabase-js';
  import { supabase } from '$lib/supabase';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { goto } from '$app/navigation';

  let sessionOk = $state<boolean | null>(null);

  async function handleConfirmedSession(session: Session) {
    if (sessionOk !== null) return;
    sessionOk = true;
    try {
      await fetch(`${import.meta.env.VITE_API_URL}/v1/athlete/onboard`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${session.access_token}`,
          'Content-Type': 'application/json',
        },
      });
    } catch {
      // Non-fatal
    }
    authStore.applySession(session);
    await goto('/onboarding', { replaceState: true });
  }

  onMount(() => {
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((event, session) => {
      if (event === 'SIGNED_IN' && session && sessionOk === null) {
        void handleConfirmedSession(session);
      }
    });

    void (async () => {
      const { data } = await supabase.auth.getSession();
      if (data.session && sessionOk === null) {
        await handleConfirmedSession(data.session);
      }
    })();

    const errorTimer = setTimeout(() => {
      if (sessionOk === null) {
        sessionOk = false;
      }
    }, 2000);

    return () => {
      subscription.unsubscribe();
      clearTimeout(errorTimer);
    };
  });
</script>

<div class="min-h-full flex flex-col p-6 items-center justify-center relative">
  <div class="absolute top-0 left-0 w-full h-[300px] bg-gradient-to-b from-[rgba(70,33,255,0.15)] to-transparent pointer-events-none"></div>
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
        <div class="w-16 h-16 rounded-2xl bg-gradient-to-br from-blue to-teal flex items-center justify-center mx-auto mb-6 shadow-[0_4px_32px_rgba(70,33,255,0.4)]">
          <span class="text-3xl font-bold text-text0">A</span>
        </div>
        <p class="text-text2 text-sm animate-pulse">Confirming your account…</p>
      </div>
    {/if}
  </div>
</div>
