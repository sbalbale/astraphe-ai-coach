<script lang="ts">
  import { page } from '$app/stores';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { ensureAuthSession } from '$lib/apiAuth';
  import AuthShell from '$lib/components/ui/AuthShell.svelte';
  import BrandMark from '$lib/components/ui/BrandMark.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import FormAlert from '$lib/components/ui/FormAlert.svelte';
  import Spinner from '$lib/components/ui/Spinner.svelte';
  import UiIcon from '$lib/components/ui/UiIcon.svelte';

  /**
   * What an approved client can read: the MCP server's read-only tools
   * (mcp-server/astraphe_mcp/tools/read_tools.py). Keep in sync if tools change.
   */
  const ACCESS_ROWS = [
    { title: 'Read your training', detail: 'Workouts, streams, load, form and zones.' },
    { title: 'Read your recovery', detail: 'Recovery, sleep and HRV summaries.' },
    { title: 'Read your plan', detail: 'Upcoming planned sessions.' },
    { title: 'Read what your coach remembers', detail: 'Goals, preferences and notes your coach has saved.' },
  ];

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

  // Opaque id from GoTrue. Validated before it goes into a request path: a crafted
  // value like "../../x" would otherwise send this user's token to another endpoint.
  const AUTHORIZATION_ID_RE = /^[A-Za-z0-9_-]{8,128}$/;
  let authorizationId = $derived.by(() => {
    const raw = $page.url.searchParams.get('authorization_id');
    return raw && AUTHORIZATION_ID_RE.test(raw) ? raw : null;
  });

  /** Where the authorization code will be sent: shown so the user can see who is asking. */
  function hostOf(url: string | undefined): string {
    try {
      return url ? new URL(url).host : '';
    } catch {
      return '';
    }
  }

  /** A fresh, valid access token (the stored one can be expired on this page). */
  async function accessToken(): Promise<string | null> {
    const session = await ensureAuthSession();
    return session?.access_token ?? null;
  }

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
    if (!authStore.session?.access_token) return; // handled by the {#if} below — waiting on sign-in
    const token = await accessToken();
    if (!token) return;

    try {
      const res = await fetch(`${SUPABASE_URL}/auth/v1/oauth/authorizations/${encodeURIComponent(authorizationId)}`, {
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
    const token = await accessToken();
    if (!token) return;

    status = 'submitting';
    try {
      const res = await fetch(
        `${SUPABASE_URL}/auth/v1/oauth/authorizations/${encodeURIComponent(authorizationId)}/consent`,
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
      // Only follow a redirect to the destination this request declared.
      const expected = details?.redirect_uri ? new URL(details.redirect_uri).origin : null;
      const target = new URL(String(body.redirect_url));
      if (!expected || target.origin !== expected) {
        throw new Error('Unexpected redirect; the connection was not completed.');
      }
      window.location.href = target.toString();
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

{#if status === 'missing_id'}
  <AuthShell centered>
    <BrandMark size={56} class="mb-8" />
    <h1 class="font-display text-[36px] leading-[1.1] text-text0 mb-4">Connect to Astraphe</h1>
    <FormAlert>This link is missing its authorization request. Ask the app you're connecting to try again.</FormAlert>
  </AuthShell>
{:else if authStore.loading || (authStore.session && status === 'loading')}
  <AuthShell centered>
    <Spinner label="Loading" />
    <p class="text-[16px] text-text2 mt-6">{authStore.loading ? 'Checking your session…' : 'Loading request…'}</p>
  </AuthShell>
{:else if !authStore.session}
  <AuthShell brand title="Connect to Astraphe" subtitle="Sign in to Astraphe to approve this connection.">
    <a
      href={`/auth/signin?redirect=${encodeURIComponent($page.url.pathname + $page.url.search)}`}
      class="inline-flex items-center justify-center w-full h-14 rounded-[18px] bg-blue text-on-accent text-[16px] font-semibold no-underline hover:bg-blue/90 transition-colors"
    >
      Sign in
    </a>
  </AuthShell>
{:else if status === 'error'}
  <AuthShell centered>
    <BrandMark size={56} class="mb-8" />
    <h1 class="font-display text-[36px] leading-[1.1] text-text0 mb-4">Couldn't connect</h1>
    <FormAlert>{errorMsg}</FormAlert>
  </AuthShell>
{:else if details}
  <AuthShell>
    <div class="flex items-center gap-4 mt-12 mb-8" aria-hidden="true">
      <div class="w-14 h-14 rounded-2xl bg-bg3 flex items-center justify-center font-mono text-[14px] text-text1">APP</div>
      <div class="w-10 border-t-2 border-dashed border-border"></div>
      <BrandMark size={56} />
    </div>

    <h1 class="font-display text-[40px] leading-[1.08] text-text0 mb-3">
      {details.client.name} wants to connect to Astraphe
    </h1>
    <p class="text-[16px] text-text2 mb-8">Signed in as {details.user.email}</p>

    <section class="bg-bg2 border border-border rounded-card px-6 py-5">
      <p class="font-mono text-[11px] tracking-[0.22em] uppercase text-text2 pb-3 border-b border-border">It will be able to</p>
      <ul class="list-none m-0 p-0">
        {#each ACCESS_ROWS as row (row.title)}
          <li class="flex gap-4 py-4 border-b border-border">
            <UiIcon name="check" size={18} class="text-blue shrink-0 mt-1" />
            <div>
              <p class="text-[16px] font-medium text-text0">{row.title}</p>
              <p class="text-[14px] text-text2 leading-relaxed">{row.detail}</p>
            </div>
          </li>
        {/each}
        <li class="flex gap-4 pt-4">
          <UiIcon name="check" size={18} class="text-blue shrink-0 mt-1" />
          <div>
            <p class="text-[16px] font-medium text-text0">Know who you are</p>
            <p class="text-[14px] text-text2 leading-relaxed">It can {describeScope(details.scope)}.</p>
          </div>
        </li>
      </ul>
      <p class="text-[14px] text-text1 leading-relaxed mt-4">Read-only: it can't change anything in your account.</p>
    </section>

    <p class="text-[14px] text-text2 leading-relaxed mt-6">
      Access will be sent to <span class="font-mono text-text0">{hostOf(details.redirect_uri) || 'an unknown address'}</span>.
      The app name is chosen by whoever registered it and isn't verified by Astraphe; only
      allow this if you started the connection yourself.
    </p>

    <div class="mt-auto pt-8 flex flex-col gap-3">
      <Button onclick={() => respond('approve')} disabled={status === 'submitting'}>
        {status === 'submitting' ? 'Connecting…' : 'Allow access'}
      </Button>
      <Button variant="secondary" onclick={() => respond('deny')} disabled={status === 'submitting'}>
        Deny
      </Button>
    </div>
  </AuthShell>
{/if}
