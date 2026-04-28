<script lang="ts">
  import '../app.css';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import Sidebar from '$lib/components/Sidebar.svelte';
  import BottomNav from '$lib/components/BottomNav.svelte';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';

  let { children } = $props();
  
  let innerWidth = $state(0);
  let wide = $derived(innerWidth >= 768);
  
  let isAuthRoute = $derived($page.url.pathname.startsWith('/auth'));

  $effect(() => {
    if (!authStore.loading) {
      if (!authStore.user && !isAuthRoute) {
        goto('/auth/signin', { replaceState: true });
      } else if (authStore.user && isAuthRoute) {
        goto('/dashboard', { replaceState: true });
      }

      if (authStore.user) {
        athleteStore.fetchAll();
      }
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
{:else if isAuthRoute}
  <div class="h-full bg-bg0 text-text0 font-sans overflow-y-auto">
    {@render children()}
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
        <div class="flex gap-1.5 px-4 pt-2.5 shrink-0">
          {#each [{id: '/recovery', label: 'Recovery'}, {id: '/sleep', label: 'Sleep'}, {id: '/strain', label: 'Strain'}] as t}
            <a href={t.id} class="px-3.5 py-1.5 rounded-full text-xs font-medium font-sans transition-all duration-200 border no-underline
              {$page.url.pathname === t.id ? 'bg-blue text-white border-blue' : 'bg-glass text-text1 border-border'}">
              {t.label}
            </a>
          {/each}
        </div>
      {/if}
    {/if}
    
    <div class="flex-1 overflow-y-auto flex flex-col relative {wide ? 'p-6 px-7' : $page.url.pathname === '/chat' ? 'p-3 px-4 pb-4' : 'p-3 px-4'}">
      {@render children()}
    </div>
    
      {#if !wide}
        <BottomNav currentPath={$page.url.pathname} />
      {/if}
    </div>
  </div>
{/if}
