<script lang="ts">
  import { authStore } from '$lib/stores/authStore.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { goto } from '$app/navigation';
  import { navTo } from '$lib/nav';
  import { latestWeightKg } from '$lib/utils/biometrics';
  import { normalizeUnits, kgToLbRoundedHalf, type Units } from '$lib/utils/units';
  import { onMount } from 'svelte';

  // Always show what's in the database, not a cached profile from an earlier session.
  onMount(() => {
    void athleteStore.refreshProfile();
    void athleteStore.fetchAll();
  });

  const units = $derived<Units>(normalizeUnits((athleteStore.profile as any)?.measurement_units));
  const thresholdPaceUnit = $derived(units === 'imperial' ? '/mi' : '/km');

  const weightKg = $derived(
    latestWeightKg(
      athleteStore.biometrics?.series,
      athleteStore.profile?.weight_kg,
      (athleteStore.profile as { latest_weight_kg?: unknown } | null)?.latest_weight_kg
    )
  );
  const weight = $derived.by(() => {
    if (weightKg == null) return { value: '--', unit: units === 'imperial' ? 'lb' : 'kg' };
    return units === 'imperial'
      ? { value: String(kgToLbRoundedHalf(weightKg)), unit: 'lb' }
      : { value: String(Math.round(weightKg)), unit: 'kg' };
  });

  const name = $derived(
    athleteStore.profile?.display_name || authStore.user?.user_metadata?.full_name || 'Athlete'
  );
  const initials = $derived.by(() => {
    const parts = String(name).trim().split(/\s+/).filter(Boolean);
    if (parts.length === 0) return 'A';
    return ((parts[0][0] ?? '') + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase();
  });

  const SPORT_LABELS: Record<string, string> = {
    bike: 'Cycling', run: 'Running', swim: 'Swimming', row: 'Rowing', strength: 'Strength', triathlon: 'Triathlon'
  };
  const focus = $derived<string[]>(
    ((athleteStore.profile as any)?.sport_focus ?? []).map((s: string) => SPORT_LABELS[s] ?? s)
  );
  const subtitle = $derived(focus.length ? `${focus.join(' · ')} focus` : authStore.user?.email || '');

  const ftp = $derived(Number(athleteStore.profile?.ftp_watts) || 0);
  const wPerKg = $derived(ftp && weightKg ? (ftp / weightKg).toFixed(1) : null);

  const connectedCount = $derived(
    Object.values(athleteStore.syncStatus?.integrations || {}).filter((i: any) => i?.connected).length
  );
  const notificationsOn = $derived(
    Object.values(((athleteStore.profile as any)?.notification_settings ?? {}) as Record<string, unknown>).filter(Boolean).length
  );

  const menu = $derived([
    { label: 'Personal info', meta: '', href: '/profile/personal-info' },
    { label: 'Training settings', meta: focus[0] ?? '', href: '/profile/training-settings' },
    { label: 'Connected apps', meta: connectedCount ? `${connectedCount} connected` : 'None', href: '/profile/connections' },
    { label: 'Notifications', meta: notificationsOn ? `${notificationsOn} on` : 'Off', href: '/profile/notifications' },
    { label: 'Privacy', meta: '', href: '/profile/privacy' }
  ]);

  const tierLabel = $derived(authStore.tier === 'premium' ? 'PREMIUM' : authStore.tier === 'trial' ? 'TRIAL' : 'FREE');

  async function handleSignOut() {
    try {
      await authStore.signOut({ timeoutMs: 4000 });
    } catch (e) {
      // Defensive: AuthState.signOut is intended not to throw, but never block navigation.
      console.warn('[profile] signOut threw unexpectedly', e);
    } finally {
      goto('/auth/signin', { replaceState: true });
    }
  }
</script>

<div class="flex flex-col gap-4 pt-1">
  <button type="button" class="self-start h-11 flex items-center gap-1 border-0 bg-transparent p-0 text-sm text-text1 cursor-pointer" onclick={() => navTo('/dashboard')}>
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m15 6-6 6 6 6"></path></svg>Today
  </button>

  <header class="flex items-center gap-4">
    <span aria-hidden="true" class="w-16 h-16 shrink-0 rounded-full bg-blue-dim border border-blue/30 flex items-center justify-center text-[22px] font-semibold text-blue">{initials}</span>
    <div class="flex-1 min-w-0 flex flex-col gap-1">
      <h1 class="m-0 font-display font-normal text-[30px] leading-none truncate">{name}</h1>
      {#if subtitle}<span class="text-[13px] text-text2 truncate">{subtitle}</span>{/if}
    </div>
    <span class="shrink-0 font-mono text-[10px] tracking-[0.12em] px-2 py-1.5 rounded-lg border border-blue/30 text-blue">{tierLabel}</span>
  </header>

  <section aria-label="Physiological profile" class="bg-bg2 border border-border rounded-[24px] px-[18px] py-4 flex flex-col gap-3">
    <div class="flex justify-between items-baseline">
      <h2 class="m-0 font-display font-normal text-[22px]">Physiology</h2>
      <button type="button" class="min-h-8 border-0 bg-transparent p-0 text-xs text-blue cursor-pointer" onclick={() => navTo('/profile/training-settings')}>Edit</button>
    </div>
    <dl class="m-0 grid grid-cols-2 gap-x-3 gap-y-3.5">
      <div><dt class="text-[11px] text-text2">FTP</dt><dd class="m-0 text-xl font-medium">{ftp || '--'} <span class="text-xs text-text2 font-normal">W{wPerKg ? ` · ${wPerKg} W/kg` : ''}</span></dd></div>
      <div><dt class="text-[11px] text-text2">Max HR</dt><dd class="m-0 text-xl font-medium">{athleteStore.profile?.max_hr ?? '--'} <span class="text-xs text-text2 font-normal">bpm</span></dd></div>
      <div><dt class="text-[11px] text-text2">Threshold pace</dt><dd class="m-0 text-xl font-medium">{athleteStore.profile?.threshold_pace || '--'} <span class="text-xs text-text2 font-normal">{thresholdPaceUnit}</span></dd></div>
      <div><dt class="text-[11px] text-text2">Weight</dt><dd class="m-0 text-xl font-medium">{weight.value} <span class="text-xs text-text2 font-normal">{weight.unit}</span></dd></div>
    </dl>
  </section>

  <nav aria-label="Account" class="bg-bg2 border border-border rounded-[24px] px-[18px] py-1 flex flex-col">
    {#each menu as item, i (item.href)}
      <button
        type="button"
        class="min-h-[52px] flex items-center gap-2.5 border-0 bg-transparent p-0 text-left text-text0 cursor-pointer {i ? 'border-t border-border' : ''}"
        onclick={() => navTo(item.href)}
      >
        <span class="flex-1 text-[15px]">{item.label}</span>
        {#if item.meta}<span class="text-xs text-text2">{item.meta}</span>{/if}
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true" class="text-text2/70"><path d="m9 6 6 6-6 6"></path></svg>
      </button>
    {/each}
  </nav>

  <button type="button" class="h-12 rounded-[14px] border border-border bg-transparent text-red text-sm font-medium cursor-pointer" onclick={handleSignOut}>Sign out</button>
  <span class="self-center font-mono text-[10px] tracking-[0.12em] text-text2/70">ASTRAPHE · OPEN SOURCE</span>
</div>
