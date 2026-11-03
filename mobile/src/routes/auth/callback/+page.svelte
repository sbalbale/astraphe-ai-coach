<script lang="ts">
  import { onMount } from 'svelte';
  import type { Session } from '@supabase/supabase-js';
  import { supabase } from '$lib/supabase';
  import { completeAuthSession } from '$lib/utils/completeAuthSession';
  import AuthShell from '$lib/components/ui/AuthShell.svelte';
  import Spinner from '$lib/components/ui/Spinner.svelte';
  import UiIcon from '$lib/components/ui/UiIcon.svelte';

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

<AuthShell centered>
  {#if sessionOk === false}
    <div class="w-14 h-14 rounded-2xl bg-red-dim border border-red/20 text-red flex items-center justify-center mb-6">
      <UiIcon name="link" size={24} />
    </div>
    <h1 class="font-display text-[36px] leading-[1.1] text-text0 mb-2">Link expired or invalid</h1>
    <p class="text-[16px] text-text2 mb-8 max-w-[32ch]">
      Confirmation links work once, on the device that requested them. Request a new one to continue.
    </p>
    <a
      href="/auth/signup"
      class="inline-flex items-center justify-center w-full h-14 rounded-[18px] border border-border text-text0 text-[16px] font-semibold no-underline hover:border-text2/60 transition-colors"
    >
      Back to sign up
    </a>
  {:else}
    <Spinner label="Confirming your account" />
    <h1 class="font-display text-[36px] leading-[1.1] text-text0 mt-8 mb-2">Confirming your account…</h1>
    <p class="text-[16px] text-text2">This only takes a moment.</p>
  {/if}
</AuthShell>
