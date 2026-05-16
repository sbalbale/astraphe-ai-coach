<script lang="ts">
  import { onMount } from 'svelte';
  import { supabase } from '$lib/supabase';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { goto } from '$app/navigation';

  let password = $state('');
  let confirmPassword = $state('');
  let loading = $state(false);
  let sessionReady = $state(false);
  let done = $state(false);
  let errorMsg = $state('');

  let awaitingUserUpdated = $state(false);
  let finishFallbackTimer: ReturnType<typeof setTimeout> | null = null;

  function markSessionReady() {
    if (sessionReady !== false) return;
    sessionReady = true;
  }

  /** Clear local session without supabase.auth.signOut() — avoids NavigatorLock contention. */
  function clearLocalAuthSession() {
    authStore.session = null;
    authStore.user = null;
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const key = localStorage.key(i);
      if (key?.startsWith('sb-') && key.includes('auth-token')) {
        localStorage.removeItem(key);
      }
    }
  }

  function completeReset() {
    if (done) return;
    done = true;
    loading = false;
    awaitingUserUpdated = false;

    if (finishFallbackTimer) {
      clearTimeout(finishFallbackTimer);
      finishFallbackTimer = null;
    }

    clearLocalAuthSession();
    goto('/auth/signin?reset=success', { replaceState: true });
  }

  onMount(() => {
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((event, session) => {
      if (event === 'PASSWORD_RECOVERY' && session && sessionReady === false) {
        markSessionReady();
      }
      if (event === 'USER_UPDATED' && awaitingUserUpdated) {
        completeReset();
      }
    });

    // Defer getSession so it doesn't race hash exchange on first paint
    const sessionTimer = setTimeout(() => {
      void supabase.auth.getSession().then(({ data }) => {
        if (data.session && sessionReady === false) {
          markSessionReady();
        }
      });
    }, 0);

    return () => {
      subscription.unsubscribe();
      clearTimeout(sessionTimer);
      if (finishFallbackTimer) clearTimeout(finishFallbackTimer);
    };
  });

  function handleUpdate(e: Event) {
    e.preventDefault();
    errorMsg = '';

    if (password !== confirmPassword) {
      errorMsg = 'Passwords do not match';
      return;
    }

    if (password.length < 8) {
      errorMsg = 'Password must be at least 8 characters';
      return;
    }

    loading = true;
    awaitingUserUpdated = true;

    // Fire-and-forget: awaiting USER_UPDATED (or fallback). Do not await — avoids lock deadlock
    // when authStore's global listener runs getUser() concurrently.
    void supabase.auth.updateUser({ password }).then(({ error }) => {
      if (error && awaitingUserUpdated) {
        awaitingUserUpdated = false;
        loading = false;
        errorMsg = error.message;
        if (finishFallbackTimer) {
          clearTimeout(finishFallbackTimer);
          finishFallbackTimer = null;
        }
      }
    });

    // If USER_UPDATED never fires (or lock stalls), proceed anyway after password likely saved
    finishFallbackTimer = setTimeout(() => {
      if (awaitingUserUpdated) {
        completeReset();
      }
    }, 2500);
  }
</script>

<div class="min-h-full flex flex-col p-6 items-center justify-center relative">
  <div class="absolute top-0 left-0 w-full h-[300px] bg-gradient-to-b from-[rgba(70,33,255,0.15)] to-transparent pointer-events-none"></div>
  <div class="absolute -top-[100px] -right-[100px] w-[300px] h-[300px] bg-teal rounded-full blur-[120px] opacity-20 pointer-events-none"></div>

  <div class="w-full max-w-sm z-10">
    {#if done}
      <div class="text-center">
        <div class="w-16 h-16 rounded-2xl bg-teal/10 border border-teal/20 flex items-center justify-center mx-auto mb-6">
          <span class="text-3xl text-teal">✓</span>
        </div>
        <h1 class="text-3xl font-bold tracking-tight mb-2">Password updated</h1>
        <p class="text-text2 text-sm">Redirecting you to sign in…</p>
      </div>
    {:else if !sessionReady}
      <div class="text-center">
        <div class="w-16 h-16 rounded-2xl bg-gradient-to-br from-blue to-teal flex items-center justify-center mx-auto mb-6 shadow-[0_4px_32px_rgba(70,33,255,0.4)]">
          <span class="text-3xl font-bold text-text0">A</span>
        </div>
        <p class="text-text2 text-sm animate-pulse">Verifying link…</p>
      </div>
    {:else}
      <div class="mb-10">
        <h1 class="text-3xl font-bold tracking-tight mb-2">Set New Password</h1>
        <p class="text-text2 text-sm">Choose a strong password for your Astrape account.</p>
      </div>

      {#if errorMsg}
        <div class="p-3 bg-red-dim border-l-2 border-red rounded-lg mb-6 text-xs text-text0 leading-relaxed">
          {errorMsg}
        </div>
      {/if}

      <form onsubmit={handleUpdate} class="flex flex-col gap-4">
        <div>
          <label for="password" class="block text-[10px] text-text2 font-mono uppercase tracking-widest mb-1.5 ml-1">New password</label>
          <input
            id="password"
            type="password"
            bind:value={password}
            required
            class="w-full px-4 py-3.5 bg-glass border border-border rounded-xl text-text0 text-sm outline-none focus:border-teal focus:bg-glass2 transition-colors placeholder:text-text2"
            placeholder="••••••••"
          />
        </div>

        <div>
          <label for="confirmPassword" class="block text-[10px] text-text2 font-mono uppercase tracking-widest mb-1.5 ml-1">Confirm password</label>
          <input
            id="confirmPassword"
            type="password"
            bind:value={confirmPassword}
            required
            class="w-full px-4 py-3.5 bg-glass border border-border rounded-xl text-text0 text-sm outline-none focus:border-teal focus:bg-glass2 transition-colors placeholder:text-text2"
            placeholder="••••••••"
          />
        </div>

        <button
          type="submit"
          disabled={loading}
          class="w-full mt-4 py-3.5 bg-teal text-bg1 font-semibold rounded-xl hover:bg-teal/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? 'Updating…' : 'Update Password'}
        </button>
      </form>
    {/if}
  </div>
</div>
