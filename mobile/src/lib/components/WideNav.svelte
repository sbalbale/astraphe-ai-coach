<script lang="ts">
  /**
   * Tablet / desktop navigation (design: WideNav). 248 px with labels, or a 76 px icon rail.
   * Five sections with 1–5 shortcuts; Training lists its sub-views; ⌘K opens the palette.
   */
  import { goto } from '$app/navigation';
  import { navTo } from '$lib/nav';
  import { activeTabFor } from '$lib/navTabs';
  import { viewport } from '$lib/stores/viewport.svelte';
  import { commandPalette } from '$lib/stores/commandPalette.svelte';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import BrandMark from '$lib/components/ui/BrandMark.svelte';
  import { WIDE_NAV } from '$lib/wideNav';

  let { currentPath, hasWorkoutParam = false }: { currentPath: string; hasWorkoutParam?: boolean } = $props();

  const collapsed = $derived(viewport.railCollapsed);
  const activeTab = $derived(activeTabFor(currentPath));

  const name = $derived(
    (athleteStore.profile?.display_name || authStore.user?.user_metadata?.full_name || 'Athlete') as string
  );
  const initials = $derived.by(() => {
    const parts = name.trim().split(/\s+/).filter(Boolean);
    if (parts.length === 0) return 'A';
    return ((parts[0][0] ?? '') + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase();
  });
  const form = $derived(Math.round(athleteStore.tsb ?? 0));
  const fitnessLine = $derived(`FITNESS ${Math.round(athleteStore.ctl ?? 0)} · FORM ${form > 0 ? '+' : ''}${form}`);

  function go(e: MouseEvent, href: string) {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    // /training?workout_id=… → back to the plain log.
    if (href === '/training' && currentPath === '/training' && hasWorkoutParam) {
      void goto('/training', { keepFocus: true, noScroll: true });
      return;
    }
    navTo(href);
  }

  function subActive(subRoutes: string[]): boolean {
    return subRoutes.includes(currentPath);
  }
</script>

<nav
  aria-label="Primary"
  class="relative z-40 flex-none h-full box-border flex flex-col gap-[18px] bg-rail border-r border-rail-border text-text0 transition-[width] duration-200 ease-out {collapsed ? 'w-[76px] px-3 pt-6 pb-5' : 'w-[248px] px-4 pt-6 pb-5'}"
>
  <div class="flex items-center gap-2.5 h-10 {collapsed ? 'justify-center' : 'px-1.5'}">
    <BrandMark size={32} />
    {#if !collapsed}<span class="font-display text-[25px] leading-none">Astraphe</span>{/if}
  </div>

  <button
    type="button"
    aria-label="Search or ask your coach (Command K)"
    aria-haspopup="dialog"
    aria-expanded={commandPalette.open}
    class="h-10 flex items-center gap-2.5 rounded-xl border border-border bg-bg2 text-text2 text-[13px] cursor-pointer {collapsed ? 'w-[52px] self-center justify-center p-0' : 'pl-3 pr-2.5'}"
    onclick={() => commandPalette.show()}
  >
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="6.5"></circle><path d="m20 20-4-4"></path></svg>
    {#if !collapsed}
      <span class="flex-1 text-left">Search or ask…</span>
      <span class="font-mono text-[10px] text-text3">⌘K</span>
    {/if}
  </button>

  <ul class="list-none m-0 p-0 flex flex-col gap-0.5">
    {#each WIDE_NAV as item (item.id)}
      {@const on = activeTab === item.id}
      <li class="flex flex-col gap-0.5">
        <a
          href={item.href}
          data-nav-key={item.key}
          aria-current={on ? 'page' : undefined}
          aria-label="{item.label} ({item.key})"
          title="{item.label} ({item.key})"
          class="min-h-[44px] flex items-center gap-3 rounded-xl text-[14px] font-medium no-underline transition-colors hover:bg-rail-hover hover:text-text0 {collapsed ? 'justify-center w-[52px] self-center px-0' : 'px-3'} {on ? 'bg-bg3 text-text0' : 'text-text1'}"
          onclick={(e) => go(e, item.href)}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="flex-none {on ? 'text-blue' : ''}"><path d={item.icon}></path></svg>
          {#if !collapsed}
            <span class="flex-1">{item.label}</span>
            {#if !on}<span class="font-mono text-[10px] text-text3">{item.key}</span>{/if}
          {/if}
        </a>
        {#if !collapsed && on && item.subs.length}
          <ul class="list-none m-0 mb-1.5 p-0 pl-[30px] flex flex-col gap-px">
            {#each item.subs as s (s.href)}
              {@const sOn = subActive(s.routes)}
              <li>
                <a
                  href={s.href}
                  aria-current={sOn ? 'page' : undefined}
                  class="min-h-[34px] flex items-center px-3 rounded-[9px] text-[13px] no-underline hover:bg-rail-hover hover:text-text0 {sOn ? 'text-text0 bg-bg2 shadow-[inset_2px_0_0_theme(colors.blue.DEFAULT)]' : 'text-text2'}"
                  onclick={(e) => go(e, s.href)}
                >{s.label}</a>
              </li>
            {/each}
          </ul>
        {/if}
      </li>
    {/each}
  </ul>

  <div class="flex-1"></div>

  <button
    type="button"
    aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
    title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
    class="h-10 flex items-center gap-3 border-0 rounded-xl bg-transparent text-text2 text-[13px] cursor-pointer hover:bg-rail-hover hover:text-text0 {collapsed ? 'w-[52px] self-center justify-center p-0' : 'px-3'}"
    onclick={() => viewport.toggleRail()}
  >
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3"></rect><path d="M9 4v16"></path><path d={collapsed ? 'm13 10 2 2-2 2' : 'm16 10-2 2 2 2'}></path></svg>
    {#if !collapsed}<span>Collapse sidebar</span>{/if}
  </button>

  <a
    href="/profile"
    aria-label="Your profile"
    aria-current={currentPath.startsWith('/profile') ? 'page' : undefined}
    class="flex items-center gap-2.5 rounded-2xl no-underline text-text0 {collapsed ? 'justify-center py-1.5' : 'p-2.5 bg-bg2 border border-border'}"
    onclick={(e) => go(e, '/profile')}
  >
    <span aria-hidden="true" class="flex-none w-9 h-9 rounded-full bg-accent-surface-avatar border border-accent-surface-border flex items-center justify-center text-[13px] font-semibold text-blue">{initials}</span>
    {#if !collapsed}
      <span class="flex-1 min-w-0 flex flex-col gap-0.5">
        <span class="text-[13px] font-medium truncate">{name}</span>
        <span class="font-mono text-[10px] text-text2">{fitnessLine}</span>
      </span>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" class="text-text3" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m9 6 6 6-6 6"></path></svg>
    {/if}
  </a>
</nav>
