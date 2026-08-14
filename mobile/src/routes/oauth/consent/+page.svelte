<script lang="ts">
  import { page } from '$app/stores';
  import { authStore } from '$lib/stores/authStore.svelte';

  // GoTrue's OAuth Server redirects here (site_url + authorization_url_path from
  // supabase/config.toml's [auth.oauth_server]) with only an opaque authorization_id —
  // not the raw OAuth params. Fetch the actual pending request from GoTrue itself.
  // See docs/MCP_SERVER.md for the full contract (verified against a live local
  // Supabase instance — there is no supabase-js client helper for this yet).
  const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL;
  const SUPABASE_KEY = import.meta.env.VITE_SUPABASE_KEY || import.meta.env.VITE_SUPABASE_ANON_KEY;

  type AuthorizationDetails = {
    authorization_id: string;
    redirect_uri: string;
    client: { id: string; name: string };
    user: { id: string; email: string };
    scope: string;
  };

  let authorizationId = $derived($page.url.searchParams.get('authorization_id'));

  let status = $state<'loading' | 'ready' | 'submitting' | 'error' | 'missing_id'>('loading');
  let errorMsg = $state('');
  let details = $state<AuthorizationDetails | null>(null);

  const SCOPE_DESCRIPTIONS: Record<string, string> = {
    openid: 'confirm who you are',
    profile: 'see your name',
    email: 'see your email address',
  };

  function describeScope(scope: string): string {
    const parts = scope
      .split(' ')
      .filter(Boolean)
      .map((s) => SCOPE_DESCRIPTIONS[s] ?? s);
    return parts.length ? parts.join(', ') : 'access basic account info';
  }

  async function loadAuthorization() {
    if (!authorizationId) {
      status = 'missing_id';
      return;
    }
    const token = authStore.session?.access_token;
    if (!token) return; // handled by the {#if} below — waiting on sign-in

    try {
      const res = await fetch(`${SUPABASE_URL}/auth/v1/oauth/authorizations/${authorizationId}`, {
        headers: { apikey: SUPABASE_KEY, Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.msg || `Request failed (${res.status})`);
      }
      details = await res.json();
      status = 'ready';
    } catch (e) {
      errorMsg = e instanceof Error ? e.message : 'Failed to load this request.';
      status = 'error';
    }
  }

  async function respond(action: 'approve' | 'deny') {
    if (!authorizationId) return;
    const token = authStore.session?.access_token;
    if (!token) return;

    status = 'submitting';
    try {
      const res = await fetch(
        `${SUPABASE_URL}/auth/v1/oauth/authorizations/${authorizationId}/consent`,
        {
          method: 'POST',
          headers: { apikey: SUPABASE_KEY, Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({ action }),
        }
      );
      const body = await res.json().catch(() => ({}));
      if (!res.ok || !body.redirect_url) {
        throw new Error(body.msg || `Request failed (${res.status})`);
      }
      window.location.href = body.redirect_url;
    } catch (e) {
      errorMsg = e instanceof Error ? e.message : 'Failed to submit your decision.';
      status = 'error';
    }
  }

  // authStore hydrates asynchronously on app load; wait for it before deciding whether
  // to show the sign-in prompt or fetch the pending request. Same top-level $effect
  // idiom as +layout.svelte's own auth-gating effect. Reads authStore.session directly
  // (not a one-shot latch) so this correctly re-fires if session populates after loading
  // flips false, instead of getting stuck forever on a race between the two.
  $effect(() => {
    if (!authorizationId) {
      status = 'missing_id';
      return;
    }
    if (authStore.loading || !authStore.session) return;
    if (status !== 'loading') return; // already fetched (or failed) — don't refetch
    void loadAuthorization();
  });
</script>

<div class="min-h-full flex flex-col p-6 items-center justify-center relative">
  <div class="absolute top-0 left-0 w-full h-[300px] bg-gradient-to-b from-[rgba(70,33,255,0.15)] to-transparent pointer-events-none"></div>
  <div class="absolute -top-[100px] -right-[100px] w-[300px] h-[300px] bg-teal rounded-full blur-[120px] opacity-20 pointer-events-none"></div>

  <div class="w-full max-w-sm z-10">
    <div class="mb-8 text-center">
      <div class="w-16 h-16 rounded-2xl bg-gradient-to-br from-blue to-teal flex items-center justify-center mx-auto mb-6 shadow-[0_4px_32px_rgba(70,33,255,0.4)]">
        <span class="text-3xl font-bold text-text0">A</span>
      </div>
      <h1 class="text-2xl font-bold tracking-tight mb-2">Connect to Astraphe</h1>
    </div>

    {#if status === 'missing_id'}
      <div class="p-3 bg-red-dim border-l-2 border-red rounded-lg text-xs text-text0 leading-relaxed text-center">
        This link is missing its authorization request. Ask the app you're connecting to try again.
      </div>
    {:else if authStore.loading}
      <p class="text-text2 text-sm text-center animate-pulse">Checking your session…</p>
    {:else if !authStore.session}
      <div class="p-3 bg-glass border border-border rounded-lg text-xs text-text0 leading-relaxed text-center mb-4">
        Sign in to Astraphe to approve this connection.
      </div>
      <a
        href={`/auth/signin?redirect=${encodeURIComponent($page.url.pathname + $page.url.search)}`}
        class="block w-full text-center px-4 py-3.5 bg-gradient-to-br from-blue to-teal rounded-xl text-text0 text-sm font-medium"
      >
        Sign In
      </a>
    {:else if status === 'loading'}
      <p class="text-text2 text-sm text-center animate-pulse">Loading request…</p>
    {:else if status === 'error'}
      <div class="p-3 bg-red-dim border-l-2 border-red rounded-lg text-xs text-text0 leading-relaxed text-center">
        {errorMsg}
      </div>
    {:else if details}
      <div class="p-4 bg-glass border border-border rounded-xl mb-6">
        <p class="text-text0 text-sm leading-relaxed">
          <span class="font-semibold">{details.client.name}</span> wants to
          {describeScope(details.scope)} for your Astraphe account
          <span class="text-text2">({details.user.email})</span>.
        </p>
        <p class="text-text2 text-xs mt-3 leading-relaxed">
          Astraphe's MCP tools are read-only in this release — this connection can read your
          training data but cannot change it.
        </p>
      </div>

      <div class="flex flex-col gap-3">
        <button
          onclick={() => respond('approve')}
          disabled={status === 'submitting'}
          class="w-full px-4 py-3.5 bg-gradient-to-br from-blue to-teal rounded-xl text-text0 text-sm font-medium disabled:opacity-50"
        >
          {status === 'submitting' ? 'Connecting…' : 'Allow'}
        </button>
        <button
          onclick={() => respond('deny')}
          disabled={status === 'submitting'}
          class="w-full px-4 py-3.5 bg-glass border border-border rounded-xl text-text2 text-sm font-medium disabled:opacity-50"
        >
          Deny
        </button>
      </div>
    {/if}
  </div>
</div>
