<script lang="ts">
  /** One notification type: switch, description, where it opens, timing and channels. */
  import ToggleSwitch from '$lib/components/ToggleSwitch.svelte';
  import { NOTIFICATION_OPTIONS, type NotificationTypePrefs } from '$lib/notificationSettings';
  import { emailCapable, type TypeMeta } from '$lib/utils/notificationUi';

  let {
    meta,
    prefs,
    first = false,
    disabled = false,
    ontoggle,
    onoption,
    onchannel
  }: {
    meta: TypeMeta;
    prefs: NotificationTypePrefs;
    first?: boolean;
    disabled?: boolean;
    ontoggle: () => void;
    onoption: (value: string) => void;
    onchannel: (channel: 'push' | 'email') => void;
  } = $props();

  const opts = $derived(NOTIFICATION_OPTIONS[meta.id]);
  const canEmail = $derived(emailCapable(meta.id));

  const chip = (on: boolean, dis = false) =>
    `min-h-9 px-3 rounded-[10px] text-[12px] font-medium ${
      dis
        ? 'bg-transparent border border-dashed border-popover-border text-text3 cursor-default'
        : on
          ? 'bg-accent-surface border border-blue text-text0 cursor-pointer'
          : 'bg-transparent border border-popover-border text-text2 cursor-pointer'
    }`;
</script>

<div class="flex flex-col py-3.5 {first ? '' : 'border-t border-rail-border'}">
  <div class="flex items-start gap-3.5">
    <span class="flex-1 flex flex-col gap-[3px] min-w-0">
      <span id="np-{meta.id}" class="text-[15px] font-medium">{meta.name}</span>
      <span class="text-[12px] leading-[1.45] text-text2">{meta.desc}</span>
      <span class="font-mono text-[10px] tracking-[0.06em] text-text3 uppercase">Opens → {meta.opens}</span>
    </span>
    <ToggleSwitch label={meta.name} checked={prefs.on} {disabled} onchange={ontoggle} />
  </div>
  {#if prefs.on}
    <div class="flex flex-col gap-2 pt-2.5">
      {#if opts}
        <div class="flex items-center gap-2.5">
          <span class="w-[58px] shrink-0 text-[12px] text-text2">{opts.label}</span>
          <div role="radiogroup" aria-label="{meta.name}: {opts.label}" class="flex-1 flex gap-1 flex-wrap">
            {#each opts.values as [value, label] (value)}
              <button type="button" role="radio" aria-checked={prefs.opt === value} {disabled} class={chip(prefs.opt === value)} onclick={() => onoption(value)}>{label}</button>
            {/each}
          </div>
        </div>
      {/if}
      <div class="flex items-center gap-2.5">
        <span class="w-[58px] shrink-0 text-[12px] text-text2">Send by</span>
        <div role="group" aria-label="{meta.name}: channels" class="flex-1 flex gap-1 flex-wrap">
          <button type="button" aria-pressed={prefs.push} {disabled} class={chip(prefs.push)} onclick={() => onchannel('push')}>Push</button>
          {#if canEmail}
            <button type="button" aria-pressed={!!prefs.email} {disabled} class={chip(!!prefs.email)} title="Saved for later: Astraphe doesn't send email notifications yet." onclick={() => onchannel('email')}>Email</button>
          {:else}
            <button type="button" disabled class={chip(false, true)} aria-label="Email isn't available for this notification">Email · n/a</button>
          {/if}
        </div>
      </div>
    </div>
  {/if}
</div>
