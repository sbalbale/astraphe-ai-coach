<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import RacePredictor from '$lib/components/RacePredictor.svelte';
  import Tag from '$lib/components/Tag.svelte';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { goto } from '$app/navigation';
  import { normalizeUnits, type Units } from '$lib/utils/units';

  const menu = [
    { label: 'Personal Information', href: '/profile/personal-info' },
    { label: 'Performance Calculators', href: '/profile/calculators' },
    { label: 'Training Settings', href: '/profile/training-settings' },
    { label: 'Connected Apps', href: '/profile/connections' },
    { label: 'Notifications', href: '/profile/notifications' },
    { label: 'Privacy', href: '/profile/privacy' }
  ];

  const units = $derived<Units>(normalizeUnits((athleteStore.profile as any)?.measurement_units));
  const thresholdPaceUnit = $derived(units === 'imperial' ? '/mile' : '/km');

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

<div class="flex flex-col gap-3">
  <div>
    <p class="text-xs text-text2 font-mono uppercase tracking-[0.1em]">Athlete Profile</p>
    <h1 class="text-[22px] font-bold tracking-[-0.02em]">Me</h1>
  </div>

  <Card style="background: linear-gradient(135deg, rgba(70,33,255,0.1), rgba(0,200,168,0.05)); text-align: center; padding-top: 24px; padding-bottom: 24px;">
    <div class="w-20 h-20 rounded-full bg-gradient-to-br from-blue to-teal flex items-center justify-center text-[32px] text-white font-bold mx-auto mb-3 shadow-[0_4px_24px_rgba(70,33,255,0.3)]">
      {athleteStore.profile?.display_name?.charAt(0)?.toUpperCase() || authStore.user?.user_metadata?.full_name?.charAt(0)?.toUpperCase() || 'M'}
    </div>
    <h2 class="text-[18px] font-bold mb-1">{athleteStore.profile?.display_name || authStore.user?.user_metadata?.full_name || 'Athlete'}</h2>
    <p class="text-xs text-text2 mb-3">{authStore.user?.email || 'No email provided'}</p>
    {#if authStore.tier === 'premium'}
      <Tag color="#00C8A8">PREMIUM</Tag>
    {:else if authStore.tier === 'trial'}
      <Tag color="#FFCB88">TRIAL</Tag>
    {:else}
      <Tag color="#94a3b8">FREE</Tag>
    {/if}
  </Card>

  <Card>
    <p class="text-[13px] font-semibold mb-3">Physiological Profile</p>
    <div class="grid grid-cols-2 gap-4">
      <div class="p-3 rounded-xl bg-glass border border-border">
        <p class="text-[11px] text-text2 uppercase tracking-wider">Max HR</p>
        <p class="mt-1 text-[16px] font-semibold font-mono text-red">
          {athleteStore.profile?.max_hr ? `${athleteStore.profile.max_hr} bpm` : '-- bpm'}
        </p>
      </div>

      <div class="p-3 rounded-xl bg-glass border border-border">
        <p class="text-[11px] text-text2 uppercase tracking-wider">FTP</p>
        <p class="mt-1 text-[16px] font-semibold font-mono text-blue">
          {athleteStore.profile?.ftp_watts ? `${athleteStore.profile.ftp_watts} W` : '-- W'}
        </p>
      </div>

      <div class="p-3 rounded-xl bg-glass border border-border">
        <p class="text-[11px] text-text2 uppercase tracking-wider">Threshold Pace</p>
        <p class="mt-1 text-[16px] font-semibold font-mono text-teal">
          {athleteStore.profile?.threshold_pace ? `${athleteStore.profile.threshold_pace} ${thresholdPaceUnit}` : `-- ${thresholdPaceUnit}`}
        </p>
      </div>

      <div class="p-3 rounded-xl bg-glass border border-border">
        <p class="text-[11px] text-text2 uppercase tracking-wider">VMA (Estimated)</p>
        <p class="mt-1 text-[16px] font-semibold font-mono text-text0">18.5 km/h</p>
      </div>
    </div>
  </Card>

  <RacePredictor ctl={Math.round(athleteStore.ctl) || 68} />

  <Card>
    <p class="text-[13px] font-semibold mb-3">Account</p>
    <div class="flex flex-col gap-1">
      {#each menu as item (item.href)}
        <a href={item.href} class="w-full flex justify-between items-center py-2.5 bg-transparent border-none text-text1 text-[13px] cursor-pointer hover:text-text0 transition-colors">
          <span>{item.label}</span>
          <span class="text-text2">→</span>
        </a>
      {/each}
    </div>
  </Card>
  
  <button
    type="button"
    onclick={handleSignOut}
    class="w-full p-3 rounded-xl bg-glass border border-border text-[13px] font-medium text-red mt-2 transition-colors hover:bg-red/10 cursor-pointer"
  >
    Sign Out
  </button>
</div>
