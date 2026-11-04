<script lang="ts">
  /**
   * Notification settings (design: NotifPrefs / PNotify / WNotify): push permission,
   * six notification types with timing and channels, quiet hours, coach texts and a test.
   * Every change saves straight away and is undone on screen if the save fails.
   */
  import { onMount } from 'svelte';
  import { Capacitor } from '@capacitor/core';
  import SubpageHeader from '$lib/components/SubpageHeader.svelte';
  import PermissionCard from '$lib/components/notifications/PermissionCard.svelte';
  import NotificationTypeRow from '$lib/components/notifications/NotificationTypeRow.svelte';
  import QuietHoursCard from '$lib/components/notifications/QuietHoursCard.svelte';
  import TextsCard from '$lib/components/notifications/TextsCard.svelte';
  import TestNotificationCard from '$lib/components/notifications/TestNotificationCard.svelte';
  import { api } from '$lib/api';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { viewport } from '$lib/stores/viewport.svelte';
  import { requestPushPermission, initPushNotifications, hasWebPushSubscription } from '$lib/services/pushNotifications';
  import { isStandaloneDisplayMode } from '$lib/utils/pwa';
  import {
    NOTIFICATION_DEFAULTS,
    effectiveNotificationPrefs,
    type NotificationPrefs,
    type NotificationTypeId
  } from '$lib/notificationSettings';
  import {
    deviceLabel,
    enablePushMessage,
    groupedTypes,
    isIosUserAgent,
    permissionNotGrantedMessage,
    permissionState,
    quietNote,
    testResultMessage,
    toggleChannel,
    toggleType as toggleTypePrefs,
    withType,
    type PermissionState
  } from '$lib/utils/notificationUi';

  let prefs = $state<NotificationPrefs>(structuredClone(NOTIFICATION_DEFAULTS));
  let loaded = $state(false);
  let saving = $state(false);
  let saveError = $state<string | null>(null);

  let perm = $state<PermissionState>('default');
  let ios = $state(false);
  let device = $state('this browser');
  let devicesCount = $state<number | null>(null);
  let enabling = $state(false);
  /** Why "Turn on notifications" didn't turn push on (null when it worked or wasn't tried). */
  let pushError = $state<string | null>(null);

  let testing = $state(false);
  let testStatus = $state<'sent' | 'no_devices' | 'rate_limited' | 'error' | null>(null);

  const groups = groupedTypes();

  async function detectPermission() {
    const ua = navigator.userAgent;
    const touch = navigator.maxTouchPoints ?? 0;
    const native = Capacitor.isNativePlatform();
    ios = isIosUserAgent(ua, touch);
    device = deviceLabel(ua, touch, native);
    let nativeStatus: 'granted' | 'denied' | 'prompt' | null = null;
    if (native) {
      try {
        const { PushNotifications } = await import('@capacitor/push-notifications');
        const s = await PushNotifications.checkPermissions();
        nativeStatus = s.receive === 'granted' ? 'granted' : s.receive === 'denied' ? 'denied' : 'prompt';
      } catch {
        nativeStatus = null;
      }
    }
    const webPermission = 'Notification' in window ? Notification.permission : null;
    perm = permissionState({
      native,
      nativeStatus,
      webPermission,
      ios,
      standalone: isStandaloneDisplayMode(),
      pushManager: 'PushManager' in window,
      // "On" needs a real subscription, not just the permission.
      subscribed: !native && webPermission === 'granted' ? await hasWebPushSubscription() : false
    });
    if (perm === 'granted') {
      const d = await api.getNotificationDevices();
      devicesCount = d ? d.count : null;
    }
  }

  onMount(async () => {
    try {
      await athleteStore.fetchAll();
    } catch {
      // defaults still render
    }
    prefs = effectiveNotificationPrefs(athleteStore.profile?.notification_settings);
    loaded = true;
    await detectPermission();
  });

  /** Optimistic save: show the change now, put it back if the server refuses it. */
  async function save(next: NotificationPrefs) {
    const prev = prefs;
    prefs = next;
    saving = true;
    saveError = null;
    const ok = await athleteStore.updateProfile({ notification_settings: $state.snapshot(next) });
    saving = false;
    if (!ok) {
      prefs = prev;
      saveError = "Couldn't save that change. Check your connection and try again.";
    }
  }

  function toggleType(id: NotificationTypeId) {
    void save(toggleTypePrefs(prefs, id));
  }

  function setOption(id: NotificationTypeId, value: string) {
    if (prefs.types[id].opt === value) return;
    void save(withType(prefs, id, { opt: value }));
  }

  function setChannel(id: NotificationTypeId, channel: 'push' | 'email') {
    const next = toggleChannel(prefs, id, channel);
    if (next) void save(next);
  }

  async function enablePush() {
    enabling = true;
    pushError = null;
    try {
      const granted = await requestPushPermission();
      const webPermission = 'Notification' in window ? Notification.permission : null;
      pushError = granted ? enablePushMessage(await initPushNotifications()) : permissionNotGrantedMessage(webPermission);
    } finally {
      enabling = false;
      await detectPermission();
    }
  }

  async function sendTest() {
    testing = true;
    testStatus = null;
    const res = await api.sendTestNotification();
    testing = false;
    testStatus = res.status;
  }

  const wide = $derived(viewport.wide);
  const testResult = $derived(testResultMessage(testStatus, device));
</script>

{#snippet sectionLabel(text: string)}
  <span class="px-1 pt-1.5 font-mono text-[11px] tracking-[0.14em] text-text2">{text}</span>
{/snippet}

<div class="flex flex-col gap-4 pb-6">
  <SubpageHeader title="Notifications" />

  {#if saveError}
    <p role="alert" class="m-0 px-4 py-3 rounded-[14px] bg-red-dim border border-red/30 text-[13px] text-red">{saveError}</p>
  {/if}

  <div class={wide ? 'grid grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] gap-5 items-start' : 'flex flex-col gap-2.5'}>
    <div class="flex flex-col gap-2.5 min-w-0">
      <PermissionCard status={perm} {device} {ios} {devicesCount} busy={enabling} onenable={enablePush} onrecheck={detectPermission} />
      {#if pushError && perm !== 'granted'}
        <p role="alert" class="m-0 px-4 py-3 rounded-[14px] bg-red-dim border border-red/30 text-[13px] text-red">{pushError}</p>
      {/if}

      {#each groups as g (g.name)}
        {@render sectionLabel(g.name)}
        <section aria-label={g.name} class="bg-bg2 border border-border rounded-[24px] px-4 flex flex-col">
          {#each g.rows as meta, i (meta.id)}
            <NotificationTypeRow
              {meta}
              prefs={prefs.types[meta.id]}
              first={i === 0}
              disabled={!loaded || saving}
              ontoggle={() => toggleType(meta.id)}
              onoption={(v) => setOption(meta.id, v)}
              onchannel={(c) => setChannel(meta.id, c)}
            />
          {/each}
        </section>
      {/each}
      <span class="px-1 text-[11px] leading-normal text-text3">Email is coming soon. For now every notification arrives as push, so turning push off turns that notification off.</span>
    </div>

    <div class="flex flex-col gap-2.5 min-w-0">
      {@render sectionLabel('QUIET HOURS')}
      <QuietHoursCard
        on={prefs.quiet.on}
        from={prefs.quiet.from}
        to={prefs.quiet.to}
        note={quietNote(prefs)}
        disabled={!loaded || saving}
        ontoggle={() => save({ ...prefs, quiet: { ...prefs.quiet, on: !prefs.quiet.on } })}
        onchange={(from, to) => save({ ...prefs, quiet: { ...prefs.quiet, from, to } })}
      />

      {@render sectionLabel('TEXT MESSAGES')}
      <TextsCard texts={prefs.texts} debriefOn={prefs.types.debrief.on} disabled={!loaded || saving} onchange={(t) => save({ ...prefs, texts: t })} />

      {@render sectionLabel('CHECK IT WORKS')}
      <TestNotificationCard enabled={perm === 'granted'} {device} sending={testing} result={testResult} onsend={sendTest} />

      <span class="px-1 text-[11px] leading-normal text-text3">We send at most one debrief per workout and nothing during quiet hours. Every notification opens the exact chat, session or page it's about.</span>
    </div>
  </div>
</div>
