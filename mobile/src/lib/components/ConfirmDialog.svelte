<script lang="ts">
  import Modal from '$lib/components/Modal.svelte';

  interface Props {
    show: boolean;
    title: string;
    message: string;
    confirmText?: string;
    cancelText?: string;
    confirmTone?: 'danger' | 'primary';
    onConfirm: () => void;
    onCancel: () => void;
  }

  let {
    show,
    title,
    message,
    confirmText = 'Confirm',
    cancelText = 'Cancel',
    confirmTone = 'primary',
    onConfirm,
    onCancel
  }: Props = $props();
</script>

<Modal show={show} title={title} onClose={onCancel}>
  {#snippet children()}
    <p class="text-[13px] text-text1 leading-relaxed">{message}</p>

    <div class="mt-5 flex gap-2 justify-end">
      <button
        type="button"
        class="px-4 py-2 rounded-xl text-[12px] bg-glass border border-border text-text1 hover:text-text0 transition-colors"
        onclick={onCancel}
      >
        {cancelText}
      </button>
      <button
        type="button"
        class="px-4 py-2 rounded-xl text-[12px] border transition-colors {confirmTone === 'danger'
          ? 'bg-red-600/90 border-red-500/60 text-white hover:bg-red-600'
          : 'bg-blue border-blue text-white hover:brightness-110'}"
        onclick={onConfirm}
      >
        {confirmText}
      </button>
    </div>
  {/snippet}
</Modal>

