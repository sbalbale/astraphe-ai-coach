<script lang="ts">
  import { MIN_PASSWORD_LENGTH } from '$lib/utils/passwordStrength';
  import { onMount } from 'svelte';
  import { supabase } from '$lib/supabase';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { goto } from '$app/navigation';
  import AuthShell from '$lib/components/ui/AuthShell.svelte';
  import TextField from '$lib/components/ui/TextField.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import FormAlert from '$lib/components/ui/FormAlert.svelte';
  import UiIcon from '$lib/components/ui/UiIcon.svelte';
  import Spinner from '$lib/components/ui/Spinner.svelte';
  import PasswordStrengthMeter from '$lib/components/ui/PasswordStrengthMeter.svelte';

  /** This page's own rule (checked in handleUpdate); the server may also enforce one. */  let password = $state('');
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

    if (password.length < MIN_PASSWORD_LENGTH) {
      errorMsg = `Password must be at least ${MIN_PASSWORD_LENGTH} characters`;
      return;
    }

    loading = true;
    awaitingUserUpdated = true;

    // Fire-and-forget: awaiting USER_UPDATED (or fallback). Do not await — avoids lock deadlock
    // when authStore's global listener runs getUser() concurrently.
    void supabase.auth.updateUser({ password }).then(({ error }) => {
      if (!awaitingUserUpdated) return;
      if (finishFallbackTimer) {
        clearTimeout(finishFallbackTimer);
        finishFallbackTimer = null;
      }
      if (error) {
        awaitingUserUpdated = false;
        loading = false;
        errorMsg = error.message;
      } else {
        // The server confirmed the new password.
        completeReset();
      }
    });

    // Never report success without confirmation: on a slow network or a rejected
    // password the old flow said "Password updated" after 2.5s and signed the user
    // out with their old password still the valid one.
    finishFallbackTimer = setTimeout(() => {
      if (awaitingUserUpdated) {
        awaitingUserUpdated = false;
        loading = false;
        errorMsg =
          "We couldn't confirm the change. Try signing in with your new password; if that doesn't work, request a new reset link.";
      }
    }, 20000);
  }
</script>

{#if done}
  <AuthShell centered>
    <div class="w-14 h-14 rounded-2xl bg-green-dim border border-green/20 text-green flex items-center justify-center mb-6">
      <UiIcon name="check" size={24} />
    </div>
    <h1 class="font-display text-[36px] leading-[1.1] text-text0 mb-2">Password updated</h1>
    <p class="text-[16px] text-text2">Redirecting you to sign in…</p>
  </AuthShell>
{:else if !sessionReady}
  <AuthShell centered>
    <Spinner label="Verifying link" />
    <h1 class="font-display text-[36px] leading-[1.1] text-text0 mt-8 mb-2">Verifying your link…</h1>
    <p class="text-[16px] text-text2">This only takes a moment.</p>
  </AuthShell>
{:else}
  <AuthShell title="Set a new password" subtitle="Choose a strong password for your Astraphe account.">
    {#if errorMsg}
      <FormAlert class="mb-6">{errorMsg}</FormAlert>
    {/if}

    <form onsubmit={handleUpdate} class="flex flex-col gap-6">
      <div>
        <TextField
          id="password"
          label="New password"
          type="password"
          autocomplete="new-password"
          bind:value={password}
          required
          aria-describedby="password-strength"
          placeholder={`At least ${MIN_PASSWORD_LENGTH} characters`}
        />
        <PasswordStrengthMeter id="password-strength" {password} minLength={MIN_PASSWORD_LENGTH} />
      </div>

      <TextField
        id="confirmPassword"
        label="Confirm password"
        type="password"
        autocomplete="new-password"
        bind:value={confirmPassword}
        required
        placeholder="••••••••"
      />

      <Button type="submit" disabled={loading} class="mt-2">
        {loading ? 'Updating…' : 'Update password'}
      </Button>
    </form>
  </AuthShell>
{/if}
