<script lang="ts">
  /** Wide layouts: the Me settings sub-nav (design: WNotify). */
  import { navTo } from '$lib/nav';

  let { current }: { current: string } = $props();

  const TABS = [
    { label: 'Profile', href: '/profile/personal-info' },
    { label: 'Connected apps', href: '/profile/connections' },
    { label: 'Training', href: '/profile/training-settings' },
    { label: 'Notifications', href: '/profile/notifications' },
    { label: 'Privacy', href: '/profile/privacy' }
  ];
</script>

<nav aria-label="Settings" class="flex gap-1 p-1 self-start rounded-[14px] bg-bg1 border border-border flex-wrap">
  {#each TABS as t (t.href)}
    <a
      href={t.href}
      aria-current={current === t.href ? 'page' : undefined}
      class="h-9 px-3.5 rounded-[10px] flex items-center text-[13px] font-medium no-underline {current === t.href ? 'bg-border text-text0' : 'text-text2 hover:bg-bg2'}"
      onclick={(e) => {
        if (e.metaKey || e.ctrlKey) return;
        e.preventDefault();
        navTo(t.href);
      }}
    >{t.label}</a>
  {/each}
</nav>
