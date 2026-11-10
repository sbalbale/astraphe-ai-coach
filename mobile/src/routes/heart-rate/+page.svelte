<script lang="ts">
  import HeartDay from '$lib/components/body/HeartDay.svelte';
  import { claimPageHeader, pageHeader } from '$lib/stores/pageHeader.svelte';
  import { viewport } from '$lib/stores/viewport.svelte';

  /** e.g. "GARMIN 2-MINUTE HEART RATE", from the day's series. */
  let sourceLabel = $state('');

  $effect(() => {
    const releaseHeader = claimPageHeader();
    pageHeader.eyebrow = 'HEART RATE';
    pageHeader.wideTitle = 'Heart rate';
    pageHeader.wideEyebrow = `BODY · ${sourceLabel || 'ALL-DAY HEART RATE'}`;
    return releaseHeader;
  });
</script>

<HeartDay wide={viewport.wide} bind:sourceLabel />
