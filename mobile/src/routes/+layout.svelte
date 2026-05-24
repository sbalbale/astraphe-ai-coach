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
  let isNoShellRoute = $derived(isAuthRoute || isOnboardingRoute);

  onMount(() => {
    // Remove the HTML-only pre-load indicator now that Svelte has mounted
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

    // Signed out: everything except /auth/* requires signin.
    if (!authStore.user) {
      if (athleteStore.initialLoadDone) athleteStore.reset();
      if (!isAuthRoute) goto('/auth/signin', { replaceState: true });
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
  <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
</svelte:head>

<!-- Show loading state briefly while checking auth -->
{#if authStore.loading}
  <div class="h-full flex items-center justify-center bg-bg0 text-text0 font-mono tracking-widest text-xs">
    ASTRAPE
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
      <!-- Mobile Header -->
      <div class="px-4 pt-3.5 pb-0 flex items-center justify-between shrink-0">
        <p class="font-mono font-bold text-sm tracking-[0.12em] text-blue">ASTRAPE</p>
        <div class="flex items-center gap-2">
          <div class="w-1.5 h-1.5 rounded-full bg-teal shadow-[0_0_6px_var(--teal)]"></div>
          <span class="text-[10px] text-text2 font-mono tracking-widest">SYNCED</span>
        </div>
      </div>
      
      <!-- Subtabs for Body screens -->
      {#if ['/recovery', '/sleep', '/strain'].includes($page.url.pathname)}
        <div class="flex gap-5 px-4 pt-2.5 border-b border-border shrink-0">
          {#each [{id: '/recovery', label: 'Recovery'}, {id: '/sleep', label: 'Sleep'}, {id: '/strain', label: 'Strain'}] as t (t.id)}
            <button
              type="button"
              class="pb-2 text-xs font-medium font-mono tracking-wide border-b-2 -mb-px bg-transparent cursor-pointer transition-all duration-200
              {$page.url.pathname === t.id ? 'border-blue text-text0' : 'border-transparent text-text2'}"
              onclick={() => navTo(t.id)}
              aria-current={$page.url.pathname === t.id ? 'page' : undefined}
            >
              {t.label}
            </button>
          {/each}
        </div>
      {:else if ['/dashboard', '/training', '/zones'].includes($page.url.pathname)}
        <div class="flex gap-5 px-4 pt-2.5 border-b border-border shrink-0">
          {#each [{id: '/dashboard', label: 'Home'}, {id: '/training', label: 'Training'}, {id: '/zones', label: 'Zones'}] as t (t.id)}
            <button
              type="button"
              class="pb-2 text-xs font-medium font-mono tracking-wide border-b-2 -mb-px bg-transparent cursor-pointer transition-all duration-200
              {$page.url.pathname === t.id ? 'border-blue text-text0' : 'border-transparent text-text2'}"
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
        </div>
      {/if}
    {/if}
    
    <div
      class="flex-1 flex flex-col relative min-h-0 {$page.url.pathname === '/chat'
        ? 'overflow-hidden p-0'
        : wide
          ? 'overflow-y-auto p-6 px-7'
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
