<script lang="ts">
  import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
  import { confirmState, closeConfirm } from '$lib/confirm';

  const state = confirmState;
</script>

{#if $state}
  <ConfirmDialog
    show={$state.open}
    title={$state.title}
    message={$state.message}
    confirmText={$state.confirmText}
    cancelText={$state.cancelText}
    confirmTone={$state.confirmTone}
    onCancel={() => closeConfirm(false)}
    onConfirm={() => closeConfirm(true)}
  />
{/if}

