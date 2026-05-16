<script lang="ts">
  import { fade, slide } from 'svelte/transition';
  
  interface Props {
    show: boolean;
    title?: string;
    onClose: () => void;
    children: import('svelte').Snippet;
  }

  let { show, title, onClose, children }: Props = $props();

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape' && show) {
      onClose();
    }
  }

  $effect(() => {
    if (show) {
      document.body.classList.add('modal-open');
    } else {
      document.body.classList.remove('modal-open');
    }
    return () => {
      document.body.classList.remove('modal-open');
    };
  });
</script>

<svelte:window onkeydown={handleKeydown} />

{#if show}
  <div 
    class="fixed inset-0 z-50 flex items-end justify-center p-0 sm:p-4 sm:items-center"
    transition:fade={{ duration: 200 }}
  >
    <!-- Backdrop -->
    <button
      type="button"
      class="absolute inset-0 bg-bg0/60 backdrop-blur-sm"
      onclick={onClose}
      aria-label="Close modal"
    ></button>

    <!-- Modal Content -->
    <div 
      class="relative w-full max-w-lg bg-bg1 border-t sm:border border-border rounded-t-3xl sm:rounded-3xl shadow-2xl overflow-hidden max-h-[90vh] flex flex-col"
      transition:slide={{ axis: 'y', duration: 300 }}
    >
      <!-- Header -->
      <div class="px-6 py-4 flex items-center justify-between border-b border-border shrink-0">
        <h2 class="text-[17px] font-bold tracking-tight">{title || 'Details'}</h2>
        <button 
          type="button" 
          class="w-8 h-8 rounded-full bg-glass flex items-center justify-center text-text2 hover:text-text0 transition-colors"
          onclick={onClose}
          aria-label="Close"
        >
          ✕
        </button>
      </div>

      <!-- Body -->
      <div class="p-6 overflow-y-auto">
        {@render children()}
      </div>
    </div>
  </div>
{/if}

<style>
  /* Prevent scrolling when modal is open */
  :global(body.modal-open) {
    overflow: hidden;
  }
</style>
