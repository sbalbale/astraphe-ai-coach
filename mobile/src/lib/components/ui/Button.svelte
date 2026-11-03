<script lang="ts">
  import type { Snippet } from 'svelte';

  /**
   * Design-system button. primary = sky fill with dark text; secondary = outlined;
   * ghost = text only. Full width by default (auth forms, empty-state cards).
   */
  let {
    variant = 'primary',
    type = 'button',
    disabled = false,
    full = true,
    size = 'lg',
    onclick,
    class: className = '',
    children,
  }: {
    variant?: 'primary' | 'secondary' | 'ghost';
    type?: 'button' | 'submit';
    disabled?: boolean;
    full?: boolean;
    size?: 'lg' | 'sm';
    onclick?: (e: MouseEvent) => void;
    class?: string;
    children: Snippet;
  } = $props();

  const base =
    'inline-flex items-center justify-center gap-2 font-semibold transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue';
  const sizes = { lg: 'h-14 px-6 rounded-[18px] text-[16px]', sm: 'h-9 px-4 rounded-xl text-[14px]' };
  const variants = {
    primary: 'bg-blue text-on-accent hover:bg-blue/90 border border-transparent',
    secondary: 'bg-transparent text-text0 border border-border hover:border-text2/60',
    ghost: 'bg-transparent text-text1 border border-transparent hover:text-text0',
  };
</script>

<button
  {type}
  {disabled}
  {onclick}
  class="{base} {sizes[size]} {variants[variant]} {full ? 'w-full' : ''} {className}"
>
  {@render children()}
</button>
