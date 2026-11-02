<script lang="ts">
  import '../app.css';
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { afterNavigate, goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import { installInAppLinkInterceptor, navTo } from '$lib/nav';
  import { isStandaloneDisplayMode } from '$lib/utils/pwa';
  import Sidebar from '$lib/components/Sidebar.svelte';
  import BottomNav from '$lib/components/BottomNav.svelte';
  import { format } from 'date-fns';
  import { pageHeader } from '$lib/stores/pageHeader.svelte';
  import DatePicker from '$lib/components/DatePicker.svelte';
  import { subtabsFor, titleFor } from '$lib/navTabs';
  import ConfirmHost from '$lib/components/ConfirmHost.svelte';
  import { analysisNavEpoch } from '$lib/analysisNavEpoch.svelte';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';

  afterNavigate(() => {
    analysisNavEpoch.bump();
  });

  /** Same pathname but ?workout_id= — plain <a href="/training"> may not navigate; force list view. */
  function onTrainingTabClick(e: MouseEvent) {
    if (
      $page.url.pathname === '/training' &&
      $page.url.searchParams.has('workout_id')
    ) {
      e.preventDefault();
      goto(resolve('/training'), { keepFocus: true, noScroll: true });
    }
  }

  const props = $props();
  
  let innerWidth = $state(0);
  let wide = $derived(innerWidth >= 768);
  let pushInitialized = false;
  
  let isAuthRoute = $derived($page.url.pathname.startsWith('/auth'));
  let isAuthFlowRoute = $derived(
    ['/auth/callback', '/auth/reset-password'].includes($page.url.pathname)
  );
  let isOnboardingRoute = $derived($page.url.pathname === '/onboarding');
  // The MCP OAuth consent screen: needs to render standalone (no Sidebar/BottomNav) and,
  // for a logged-out visitor, must NOT be redirected to /auth/signin the way every other
  // route is below — that redirect drops the ?authorization_id= query param, permanently
  // losing the pending OAuth request. See mobile/src/routes/oauth/consent/+page.svelte
  // and docs/MCP_SERVER.md.
  let isOAuthRoute = $derived($page.url.pathname.startsWith('/oauth/'));
  let isNoShellRoute = $derived(isAuthRoute || isOnboardingRoute || isOAuthRoute);
  let mobileSubtabs = $derived(subtabsFor($page.url.pathname));
  let headerTitle = $derived(titleFor($page.url.pathname));
  let avatarInitials = $derived.by(() => {
    const name: string =
      athleteStore.profile?.display_name || authStore.user?.user_metadata?.full_name || '';
    const parts = name.trim().split(/\s+/).filter(Boolean);
    if (parts.length === 0) return 'A';
    return ((parts[0][0] ?? '') + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase();
  });
  /** Logo header already adds bottom spacing; skip duplicate top pad on these pages. */
  const mobileTightContentTopRoutes = ['/profile', '/plan'];
  let hasMobileTightContentTop = $derived(mobileTightContentTopRoutes.includes($page.url.pathname));

  onMount(() => {
    // Remove the HTML-only pre-load indicator once Svelte has mounted
    document.getElementById('pre-load')?.remove();

    if (isStandaloneDisplayMode()) {
      document.documentElement.classList.add('pwa-standalone');
    }
    const removeLinkInterceptor = installInAppLinkInterceptor();

    // Dynamic import so a Capacitor bridge error can't crash the layout
    let cleanup: (() => void) | null = null;
    import('@capacitor/app')
      .then(({ App }) =>
        App.addListener('appUrlOpen', ({ url }) => {
          try {
            const parsed = new URL(url);
            const hash = parsed.hash ?? '';
            if (parsed.host === 'auth' && parsed.pathname === '/callback') {
              goto('/auth/callback' + hash);
            } else if (parsed.host === 'auth' && parsed.pathname === '/reset-password') {
              goto('/auth/reset-password' + hash);
            } else if (parsed.pathname.startsWith('/auth/callback')) {
              goto('/auth/callback' + hash);
            } else if (parsed.pathname.startsWith('/auth/reset-password')) {
              goto('/auth/reset-password' + hash);
            }
          } catch {
            // Malformed URL — ignore
          }
        })
      )
      .then((handle) => { cleanup = () => handle.remove(); })
      .catch(() => { /* Not in Capacitor context */ });

    return () => {
      removeLinkInterceptor();
      cleanup?.();
    };
  });

  const profileComplete = $derived.by(() => {
    const p = athleteStore.profile;
    const sport0 = typeof p?.sport_focus?.[0] === 'string' ? p.sport_focus[0].trim() : '';
    const mu = typeof p?.measurement_units === 'string' ? p.measurement_units.trim() : '';
    const tf = typeof p?.time_format === 'string' ? p.time_format.trim() : '';
    const dob = typeof p?.date_of_birth === 'string' ? p.date_of_birth.trim() : '';
    const g = typeof p?.gender === 'string' ? p.gender.trim() : '';
    const w = Number(p?.weight_kg);
    const h = Number(p?.height_cm);
    return (
      !!sport0 &&
      !!mu &&
      !!tf &&
      !!dob &&
      !!g &&
      Number.isFinite(w) &&
      w > 0 &&
      Number.isFinite(h) &&
      h > 0
    );
  });

  $effect(() => {
    if (authStore.loading) return;

    // Signed out: everything except /auth/* and /oauth/* requires signin. /oauth/consent
    // handles its own sign-in prompt (preserving ?authorization_id=) rather than being
    // bounced to /auth/signin here, which would drop it.
    if (!authStore.user) {
      if (athleteStore.initialLoadDone) athleteStore.reset();
      if (!isAuthRoute && !isOAuthRoute) goto('/auth/signin', { replaceState: true });
      return;
    }

    // Signed in: ensure profile loads before deciding redirects.
    athleteStore.fetchAll();
    if (athleteStore.loading || !athleteStore.initialLoadDone) return;

    // Register push token once per session — dynamic import keeps Capacitor out of the main bundle
    if (!pushInitialized) {
      pushInitialized = true;
      import('$lib/services/pushNotifications')
        .then(({ initPushNotifications }) => initPushNotifications())
        .catch(() => {});
    }

    const complete = profileComplete;

    // Signed in but on an auth route: onboarding until profile is complete, then home.
    // Exempt callback/reset-password so email deep-link flows can complete.
    if (isAuthRoute && !isAuthFlowRoute) {
      goto(complete ? '/dashboard' : '/onboarding', { replaceState: true });
      return;
    }

    // Onboarding is optional; if the profile is complete, leave the onboarding screen.
    if (complete && isOnboardingRoute) {
      goto('/dashboard', { replaceState: true });
      return;
    }
  });
</script>

<svelte:window bind:innerWidth />

<svelte:head>
  <link href="https://fonts.googleapis.com/css2?family=Instrument+Serif&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
</svelte:head>

<!-- Show loading state briefly while checking auth -->
{#if authStore.loading}
  <div class="h-full flex items-center justify-center bg-bg0 text-text0 font-mono tracking-widest text-xs">
    ASTRAPHE
  </div>
{:else if isNoShellRoute}
  <div class="h-full bg-bg0 text-text0 font-sans overflow-y-auto">
    {@render props.children()}
  </div>
{:else}
  <div class="flex h-full overflow-hidden bg-bg0 text-text0 font-sans">
    {#if wide}
      <Sidebar currentPath={$page.url.pathname} />
    {/if}
    
    <div class="flex-1 flex flex-col overflow-hidden relative bg-bg0">
      {#if !wide}
      <!-- Mobile Header: serif page title + avatar (Me) -->
      <div class="px-5 pt-4 {mobileSubtabs ? 'pb-3' : 'pb-2'} flex {pageHeader.dateMax ? 'items-center' : 'items-end'} justify-between shrink-0">
        <div class="flex flex-col gap-1">
          {#if $page.url.pathname === '/dashboard'}
            <span class="font-mono text-[11px] tracking-[0.14em] text-text2 uppercase">{format(new Date(), 'EEE dd MMM')}</span>
          {:else if pageHeader.eyebrow}
            <span class="font-mono text-[11px] tracking-[0.14em] text-text2 uppercase">{pageHeader.eyebrow}</span>
          {/if}
          <h1 class="font-display text-[36px] leading-none text-text0">{headerTitle}</h1>
        </div>
        {#if pageHeader.dateMax}
          <!-- Day stepper (‹ calendar · label ›) plus a Today shortcut, as in the Body designs. -->
          <div class="flex items-center gap-2">
            <div class="flex items-center h-11 rounded-[14px] border border-border bg-bg2 px-1">
              <button type="button" aria-label="Previous day" class="w-8 h-9 border-0 bg-transparent text-text1 flex items-center justify-center cursor-pointer" onclick={pageHeader.prev}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m15 6-6 6 6 6"></path></svg>
              </button>
              <div class="min-w-[84px]">
                <DatePicker bind:value={pageHeader.dateValue} max={pageHeader.dateMax} label={pageHeader.dateLabel} hideChevron ariaLabel="Pick a date" buttonClass="h-9 px-1 justify-center gap-1.5 rounded-[10px] bg-transparent border-0 text-[13px] font-semibold text-text0" popoverClass="!left-auto right-0" />
              </div>
              <button type="button" aria-label="Next day" disabled={!pageHeader.canNext} class="w-8 h-9 border-0 bg-transparent flex items-center justify-center {pageHeader.canNext ? 'text-text1 cursor-pointer' : 'text-text2/40 cursor-not-allowed'}" onclick={pageHeader.next}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m9 6 6 6-6 6"></path></svg>
              </button>
            </div>
            <button type="button" disabled={!pageHeader.canNext} class="h-11 px-3 rounded-[14px] border border-border bg-transparent text-[13px] font-medium {pageHeader.canNext ? 'text-text0 cursor-pointer' : 'text-text2/60 cursor-default'}" onclick={pageHeader.today ?? undefined}>Today</button>
          </div>
        {:else if pageHeader.add}
          <button type="button" aria-label={pageHeader.addLabel} class="w-11 h-11 rounded-[14px] border-0 bg-blue text-[#0B1420] flex items-center justify-center cursor-pointer" onclick={pageHeader.add}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"></path></svg>
          </button>
        {:else if pageHeader.segments.length}
          <div role="tablist" aria-label="Period" class="flex gap-0.5 p-[3px] h-11 rounded-[14px] bg-bg2 border border-border">
            {#each pageHeader.segments as seg (seg.value)}
              <button type="button" role="tab" aria-selected={pageHeader.segment === seg.value} class="px-3.5 border-0 rounded-[11px] text-[13px] font-medium cursor-pointer {pageHeader.segment === seg.value ? 'bg-bg3 text-text0' : 'bg-transparent text-text2'}" onclick={() => pageHeader.onSegment?.(seg.value)}>{seg.label}</button>
            {/each}
          </div>
        {/if}
        <!-- The design only shows the profile avatar on Today. -->
        {#if $page.url.pathname === '/dashboard'}
          <button
            type="button"
            class="w-11 h-11 rounded-full bg-blue-dim border border-blue/30 flex items-center justify-center text-sm font-semibold text-blue cursor-pointer"
            onclick={() => navTo('/profile')}
            aria-label="Your profile"
          >
            {avatarInitials}
          </button>
        {/if}
      </div>

      <!-- Sub-tabs for grouped tabs (Training: Log/Zones · Body: Recovery/Sleep/Strain) -->
      {#if mobileSubtabs}
        <nav
          aria-label="{headerTitle} views"
          class="mx-4 mb-1 grid gap-1 p-1 rounded-[14px] bg-bg2 border border-border shrink-0"
          style="grid-template-columns: repeat({mobileSubtabs.length}, minmax(0, 1fr));"
        >
          {#each mobileSubtabs as t (t.id)}
            <button
              type="button"
              class="h-9 rounded-[10px] text-[13px] font-medium border-none cursor-pointer transition-colors duration-200
              {$page.url.pathname === t.id ? 'bg-bg3 text-text0' : 'bg-transparent text-text2'}"
              onclick={(e) => {
                if (t.id === '/training') {
                  onTrainingTabClick(e);
                  if (!e.defaultPrevented && $page.url.pathname !== '/training') {
                    navTo('/training');
                  }
                } else {
                  navTo(t.id);
                }
              }}
              aria-current={$page.url.pathname === t.id ? 'page' : undefined}
            >
              {t.label}
            </button>
          {/each}
        </nav>
      {/if}
    {/if}
    
    <div
      class="flex-1 flex flex-col relative min-h-0 {$page.url.pathname === '/chat'
        ? 'overflow-hidden p-0'
        : wide
          ? 'overflow-y-auto p-6 px-7'
          : hasMobileTightContentTop
            ? 'overflow-y-auto px-4 pb-3 pt-0'
            : 'overflow-y-auto p-3 px-4'}"
    >
      {@render props.children()}
    </div>
    
      {#if !wide}
        <BottomNav currentPath={$page.url.pathname} />
      {/if}
    </div>
  </div>
{/if}

<ConfirmHost />
