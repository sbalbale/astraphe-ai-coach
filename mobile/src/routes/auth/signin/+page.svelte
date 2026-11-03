<script lang="ts">
  /** Same-origin in-app paths only. `/\evil.com` passed the old check and browsers treat it as //evil.com. */
  function safeRedirect(raw: string | null): string {
    if (!raw || !raw.startsWith('/') || raw.startsWith('//') || raw.includes('\\')) return '/dashboard';
    try {
      const u = new URL(raw, window.location.origin);
      return u.origin === window.location.origin ? u.pathname + u.search + u.hash : '/dashboard';
    } catch {
      return '/dashboard';
    }
  }
  import { supabase } from '$lib/supabase';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import AuthShell from '$lib/components/ui/AuthShell.svelte';
  import TextField from '$lib/components/ui/TextField.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import FormAlert from '$lib/components/ui/FormAlert.svelte';

  let resetSuccess = $derived($page.url.searchParams.get('reset') === 'success');

  let email = $state('');
  let password = $state('');
  let loading = $state(false);
  let errorMsg = $state('');

  async function handleSignIn(e: Event) {
    e.preventDefault();
    loading = true;
    errorMsg = '';

    const { data, error } = await supabase.auth.signInWithPassword({
      email,
      password,
    });

    if (error) {
      errorMsg = error.message;
      loading = false;
      return;
    }

    // Use the session returned by sign-in — Safari can return null from getSession()
    // for a moment after login, which caused a redirect loop back to this page.
    if (data.session) {
      authStore.applySession(data.session);
    } else {
      await authStore.refreshSession();
    }
    // Used by the MCP OAuth consent screen (/oauth/consent) to send the user back to
    // the pending authorization request after signing in, instead of always /dashboard.
    // Only same-origin relative paths are honored — never redirect off-app.
    const target = safeRedirect($page.url.searchParams.get('redirect'));
    try {
      await goto(target, { replaceState: true });
    } catch {
      await goto('/dashboard', { replaceState: true }).catch(() => {});
    } finally {
      loading = false;
    }
  }
</script>

<AuthShell brand title="Welcome back." subtitle="Sign in to sync your coaching data.">
  {#if resetSuccess}
    <FormAlert tone="success" class="mb-6">Password updated. Sign in with your new password.</FormAlert>
  {/if}

  {#if errorMsg}
    <FormAlert class="mb-6">{errorMsg}</FormAlert>
  {/if}

  <form onsubmit={handleSignIn} class="flex flex-col gap-6">
    <TextField
      id="email"
      label="Email"
      type="email"
      autocomplete="email"
      bind:value={email}
      required
      placeholder="athlete@example.com"
    />

    <TextField
      id="password"
      label="Password"
      type="password"
      autocomplete="current-password"
      bind:value={password}
      required
      placeholder="••••••••"
    >
      {#snippet labelAside()}
        <a href="/auth/forgot-password" class="text-[14px] text-blue no-underline hover:underline">Forgot?</a>
      {/snippet}
    </TextField>

    <Button type="submit" disabled={loading} class="mt-2">
      {loading ? 'Signing in…' : 'Sign in'}
    </Button>
  </form>

  {#snippet footer()}
    <p class="text-[16px] text-text2">
      New to Astraphe? <a href="/auth/signup" class="text-text0 font-medium no-underline hover:text-blue">Create an account</a>
    </p>
  {/snippet}
</AuthShell>
