<script lang="ts">
  import '../app.css';
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { afterNavigate, goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import { installInAppLinkInterceptor, navTo } from '$lib/nav';
  import { isStandaloneDisplayMode } from '$lib/utils/pwa';
  import WideNav from '$lib/components/WideNav.svelte';
  import CommandPalette from '$lib/components/CommandPalette.svelte';
  import { viewport } from '$lib/stores/viewport.svelte';
  import { commandPalette } from '$lib/stores/commandPalette.svelte';
  import { WIDE_NAV } from '$lib/wideNav';
  import BottomNav from '$lib/components/BottomNav.svelte';
  import { format } from 'date-fns';
  import { pageHeader } from '$lib/stores/pageHeader.svelte';
  import { isProfileComplete } from '$lib/utils/profile';
  import DatePicker from '$lib/components/DatePicker.svelte';
  import { subtabsFor, titleFor } from '$lib/navTabs';
  import ConfirmHost from '$lib/components/ConfirmHost.svelte';
  import { analysisNavEpoch } from '$lib/analysisNavEpoch.svelte';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { clearUserScopedState } from '$lib/stores/userSession';
  import { authLinkTarget, sessionFromAuthLink } from '$lib/authDeepLink';

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
  $effect.pre(() => {
    viewport.width = innerWidth;
  });
  let wide = $derived(viewport.wide);
  let pushInitialized = false;
  // Plain (non-reactive) so writing it never re-runs the effect that reads it.
  let lastUserId: string | null = null;
  
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
  /** Workout detail (map hero) and Me pages draw their own header, so the page header steps aside. */
  let hidePageHeader = $derived(
    ($page.url.pathname === '/training' && $page.url.searchParams.has('workout_id')) || $page.url.pathname.startsWith('/profile') || $page.url.pathname === '/readiness'
  );
  let mobileSubtabs = $derived(subtabsFor($page.url.pathname));
  /** Wide layouts: pages with their own header (workout detail, Me, Readiness, Coach, …) opt out. */
  let showWideHeader = $derived(!hidePageHeader && !pageHeader.hideOnWide && $page.url.pathname !== '/chat');
  let wideEyebrow = $derived(
    pageHeader.wideEyebrow ||
      pageHeader.eyebrow ||
      ($page.url.pathname === '/dashboard' ? format(new Date(), 'EEEE d MMMM') : '')
  );

  /** Wide layouts: Cmd/Ctrl+K opens the palette; 1-5 jump to a section when not typing. */
  function onGlobalKey(e: KeyboardEvent) {
    if (!wide || isNoShellRoute || !authStore.user) return;
    if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
      e.preventDefault();
      commandPalette.toggle();
      return;
    }
    if (commandPalette.open || e.metaKey || e.ctrlKey || e.altKey || e.repeat) return;
    const t = e.target as HTMLElement | null;
    if (t && (t.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName))) return;
    if (document.querySelector('[role="dialog"][aria-modal="true"]')) return;
    const item = WIDE_NAV.find((n) => n.key === e.key);
    if (item) {
      e.preventDefault();
      navTo(item.href);
    }
  }
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
        App.addListener('appUrlOpen', async ({ url }) => {
          try {
            const parsed = new URL(url);
            const target = authLinkTarget(parsed);
            if (!target) return;
            // Create the session from the link here: supabase-js only reads the URL
            // when it starts, so a link that opens the running app never signed in
            // (the callback said "Link expired", reset sat on "Verifying link…").
            await sessionFromAuthLink(parsed).catch(() => false);
            await goto(target, { replaceState: true });
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

  const profileComplete = $derived(isProfileComplete(athleteStore.profile));

  $effect(() => {
    if (authStore.loading) return;

    // Signed out: everything except /auth/* and /oauth/* requires signin. /oauth/consent
    // handles its own sign-in prompt (preserving ?authorization_id=) rather than being
    // bounced to /auth/signin here, which would drop it.
    const uid = authStore.user?.id ?? null;
    if (uid !== lastUserId) {
      // Sign-out or a different account on this device: forget the previous user's
      // data and register push for the new one.
      if (lastUserId !== null) clearUserScopedState();
      lastUserId = uid;
      pushInitialized = false;
    }

    if (!authStore.user) {
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

<svelte:window bind:innerWidth onkeydown={onGlobalKey} />

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
      <WideNav currentPath={$page.url.pathname} hasWorkoutParam={$page.url.searchParams.has('workout_id')} />
      <CommandPalette left={viewport.railCollapsed ? 92 : 264} />
    {/if}

    <div class="flex-1 flex flex-col overflow-hidden relative bg-bg0">
      {#if !wide && !hidePageHeader}
      <!-- Mobile Header: serif page title + avatar (Me) -->
      <div class="px-5 pt-4 {mobileSubtabs ? 'pb-3' : 'pb-2'} flex {pageHeader.dateMax ? 'items-center' : 'items-end'} justify-between shrink-0">
        <div class="flex flex-col gap-1">
          {#if $page.url.pathname === '/dashboard'}
            <span class="font-mono text-[11px] tracking-[0.14em] text-text2 uppercase">{format(new Date(), 'EEE dd MMM')}</span>
          {:else if pageHeader.eyebrow}
            <span class="font-mono text-[11px] tracking-[0.14em] text-text2 uppercase">{pageHeader.eyebrow}</span>
          {/if}
          <h1 class="font-display text-[36px] leading-none text-text0">{pageHeader.title || headerTitle}</h1>
        </div>
        {@render headerControls(false)}
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

    {#if wide && showWideHeader}
      <!-- Wide header (design: 44 px serif title, 12 px mono eyebrow, controls on the right) -->
      <header class="relative z-20 px-10 pt-8 pb-6 flex justify-between items-end gap-6 shrink-0">
        <div class="flex flex-col gap-1.5 min-w-0">
          {#if wideEyebrow}
            <span class="font-mono text-[12px] tracking-[0.14em] text-text2 uppercase truncate">{wideEyebrow}</span>
          {/if}
          <h1 class="m-0 font-display font-normal text-[44px] leading-none text-text0 truncate">{pageHeader.wideTitle || pageHeader.title || headerTitle}</h1>
        </div>
        {@render headerControls(true)}
      </header>
    {/if}

    <div
      class="flex-1 flex flex-col relative min-h-0 {$page.url.pathname === '/chat'
        ? 'overflow-hidden p-0'
        : wide
          ? showWideHeader
            ? 'overflow-y-auto px-10 pb-8 pt-0'
            : 'overflow-y-auto px-10 py-8'
          : hasMobileTightContentTop || hidePageHeader
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

{#snippet headerControls(isWide: boolean)}
  {#if pageHeader.dateMax}
    <!-- Day stepper (‹ calendar · label ›) plus a Today shortcut (design: DateBar). -->
    <div class="flex items-center {isWide ? 'gap-1.5 w-[268px]' : 'gap-2'}">
      <div class="flex items-center border border-border bg-bg2 {isWide ? 'flex-1 h-10 rounded-xl' : 'h-11 rounded-[14px] px-1'}">
        <button type="button" aria-label="Previous day" class="{isWide ? 'w-9 h-10' : 'w-8 h-9'} border-0 bg-transparent text-text1 flex items-center justify-center cursor-pointer" onclick={pageHeader.prev}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m15 6-6 6 6 6"></path></svg>
        </button>
        <div class={isWide ? 'flex-1' : 'min-w-[84px]'}>
          <DatePicker bind:value={pageHeader.dateValue} max={pageHeader.dateMax} label={pageHeader.dateLabel} marked={pageHeader.dateMarks} hideChevron ariaLabel="Pick a date" buttonClass="{isWide ? 'h-10 w-full' : 'h-9'} px-1 justify-center gap-1.5 rounded-[10px] bg-transparent border-0 text-[13px] font-semibold text-text0" popoverClass={isWide ? '!right-0 !left-auto mt-2' : '!fixed !left-1/2 -translate-x-1/2 !top-auto mt-2'} />
        </div>
        <button type="button" aria-label="Next day" disabled={!pageHeader.canNext} class="{isWide ? 'w-9 h-10' : 'w-8 h-9'} border-0 bg-transparent flex items-center justify-center {pageHeader.canNext ? 'text-text1 cursor-pointer' : 'text-text2/40 cursor-not-allowed'}" onclick={pageHeader.next}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m9 6 6 6-6 6"></path></svg>
        </button>
      </div>
      <button type="button" disabled={!pageHeader.canNext} class="{isWide ? 'h-10 rounded-xl' : 'h-11 rounded-[14px]'} px-3 text-[13px] font-semibold {pageHeader.canNext ? 'border-0 bg-blue text-on-accent cursor-pointer' : 'border border-border bg-transparent text-text2/60 cursor-default'}" onclick={pageHeader.today ?? undefined}>Today</button>
    </div>
  {:else if pageHeader.add}
    <button type="button" aria-label={pageHeader.addLabel} class="w-11 h-11 rounded-[14px] border-0 bg-blue text-on-accent flex items-center justify-center cursor-pointer" onclick={pageHeader.add}>
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"></path></svg>
    </button>
  {:else if pageHeader.actions.length}
    <div class="flex items-center gap-2">
      {#each pageHeader.actions as action (action.key)}
        <button
          type="button"
          aria-label={action.label}
          data-header-action={action.key}
          class="w-11 h-11 rounded-[14px] border border-border bg-transparent text-text0 flex items-center justify-center cursor-pointer"
          onclick={action.onclick}
        >
          {#if action.icon === 'history'}
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"></path><path d="M3 3v5h5M12 7v5l3 2"></path></svg>
          {:else}
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"></path></svg>
          {/if}
        </button>
      {/each}
    </div>
  {:else if pageHeader.segments.length}
    <div role="tablist" aria-label="Period" class="flex gap-0.5 p-[3px] {isWide ? 'h-10 rounded-xl' : 'h-11 rounded-[14px]'} bg-bg2 border border-border">
      {#each pageHeader.segments as seg (seg.value)}
        <button type="button" role="tab" aria-selected={pageHeader.segment === seg.value} class="px-3.5 border-0 rounded-[10px] text-[13px] font-medium cursor-pointer {pageHeader.segment === seg.value ? 'bg-bg3 text-text0' : 'bg-transparent text-text2'}" onclick={() => pageHeader.onSegment?.(seg.value)}>{seg.label}</button>
      {/each}
    </div>
  {/if}
{/snippet}

<ConfirmHost />
