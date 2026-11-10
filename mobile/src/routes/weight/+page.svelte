<script lang="ts">
  import WeightView from '$lib/components/body/WeightView.svelte';
  import { claimPageHeader, pageHeader } from '$lib/stores/pageHeader.svelte';
  import { viewport } from '$lib/stores/viewport.svelte';

  $effect(() => {
    const releaseHeader = claimPageHeader();
    pageHeader.eyebrow = 'WEIGHT';
    pageHeader.wideTitle = 'Weight';
    pageHeader.wideEyebrow = 'BODY · WEIGH-INS AND TREND';
    return releaseHeader;
  });
</script>

<WeightView wide={viewport.wide} />
