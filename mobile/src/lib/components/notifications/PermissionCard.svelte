<script lang="ts">
  /** Push permission card (design: NotifPrefs): install → turn on → blocked → on. */
  import type { PermissionState } from '$lib/utils/notificationUi';
  import { devicesLine } from '$lib/utils/notificationUi';

  let {
    status,
    device,
    ios,
    devicesCount = null,
    busy = false,
    onenable,
    onrecheck
  }: {
    status: PermissionState;
    device: string;
    ios: boolean;
    devicesCount?: number | null;
    busy?: boolean;
    onenable: () => void;
    onrecheck: () => void;
  } = $props();

  let showSteps = $state(false);

  const copy = $derived.by(() => {
    switch (status) {
      case 'install':
        return {
          title: 'Add Astraphe to your Home Screen first',
          text: 'On iPhone, web push only works when Astraphe is opened from its Home Screen icon, not from a Safari tab.'
        };
      case 'default':
        return {
          title: `Turn on push for ${device}`,
          text: 'Debriefs, readiness and plan changes arrive as notifications. You can fine-tune each one below.'
        };
      case 'denied':
        return {
          title: 'Notifications are blocked',
          text: ios
            ? 'Open iPhone Settings → Notifications → Astraphe and turn on Allow Notifications.'
            : 'Your browser is blocking Astraphe. Click the lock icon next to the address, set Notifications to Allow, then come back.'
        };
      case 'granted':
        return { title: `Push is on for ${device}`, text: devicesLine(devicesCount) };
      default:
        return {
          title: "This browser can't show notifications",
          text: 'Open Astraphe in a current Chrome, Edge, Firefox or Safari, or from the Home Screen app, to get push notifications.'
        };
    }
  });

  const tone = $derived(
    status === 'granted'
      ? { card: 'bg-green-dim border-green/40', icon: 'text-green' }
      : status === 'denied'
        ? { card: 'bg-red-dim border-red/40', icon: 'text-red' }
        : status === 'install' || status === 'unsupported'
          ? { card: 'bg-amber-dim border-amber/40', icon: 'text-amber' }
          : { card: 'bg-accent-surface border-accent-surface-border', icon: 'text-blue' }
  );

  const STEPS = ['Tap the Share button in Safari’s toolbar', 'Choose “Add to Home Screen”, then Add', 'Open Astraphe from the new icon and come back here'];
</script>

<section aria-label="Push permission" class="flex flex-col gap-3 p-4 rounded-[20px] border {tone.card}">
  <div class="flex gap-3 items-start">
    <span aria-hidden="true" class="flex-none w-9 h-9 rounded-[11px] bg-bg0 flex items-center justify-center {tone.icon}">
      {#if status === 'granted'}
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12 5 5 9-10"></path></svg>
      {:else if status === 'denied'}
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M6 8a6 6 0 0 1 9.3-5M18 8c0 7 3 9 3 9H9"></path><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0M3 3l18 18"></path></svg>
      {:else if status === 'install'}
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12M7 8l5-5 5 5"></path><path d="M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6"></path></svg>
      {:else}
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9"></path><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"></path></svg>
      {/if}
    </span>
    <span class="flex-1 flex flex-col gap-1">
      <span class="text-[15px] font-semibold">{copy.title}</span>
      <span class="text-[13px] leading-normal text-text1">{copy.text}</span>
    </span>
  </div>

  {#if status === 'install' && showSteps}
    <ol class="m-0 p-0 pl-1 list-none flex flex-col gap-2">
      {#each STEPS as s, i (s)}
        <li class="flex gap-2.5 items-center text-[13px]">
          <span class="flex-none w-6 h-6 rounded-full bg-border flex items-center justify-center font-mono text-[11px]">{i + 1}</span>{s}
        </li>
      {/each}
    </ol>
  {/if}

  {#if status === 'install'}
    <div class="flex gap-2 flex-wrap">
      <button type="button" class="min-h-11 px-4 rounded-xl border-0 bg-blue text-on-accent text-sm font-semibold cursor-pointer" onclick={() => (showSteps ? onrecheck() : (showSteps = true))}>
        {showSteps ? 'I’ve added it' : 'Show me how'}
      </button>
      {#if showSteps}
        <button type="button" class="min-h-11 px-4 rounded-xl border border-popover-border bg-transparent text-text0 text-sm font-medium cursor-pointer" onclick={() => (showSteps = false)}>Not now</button>
      {/if}
    </div>
  {:else if status === 'default'}
    <div class="flex gap-2 flex-wrap">
      <button type="button" disabled={busy} class="min-h-11 px-4 rounded-xl border-0 bg-blue text-on-accent text-sm font-semibold cursor-pointer disabled:opacity-50" onclick={onenable}>
        {busy ? 'Waiting for permission…' : 'Turn on notifications'}
      </button>
    </div>
  {:else if status === 'denied'}
    <div class="flex gap-2 flex-wrap">
      <button type="button" class="min-h-11 px-4 rounded-xl border border-popover-border bg-transparent text-text0 text-sm font-medium cursor-pointer" onclick={onrecheck}>I’ve turned it on</button>
    </div>
  {/if}
</section>
