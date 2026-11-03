<script lang="ts">
  import { supabase } from '$lib/supabase';
  import { authRedirectUrl } from '$lib/utils/redirectUrl';
  import AuthShell from '$lib/components/ui/AuthShell.svelte';
  import TextField from '$lib/components/ui/TextField.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import FormAlert from '$lib/components/ui/FormAlert.svelte';
  import UiIcon from '$lib/components/ui/UiIcon.svelte';

  let email = $state('');
  let loading = $state(false);
  let sent = $state(false);
  let errorMsg = $state('');

  async function handleReset(e: Event) {
    e.preventDefault();
    loading = true;
    errorMsg = '';

    const { error } = await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: authRedirectUrl('reset-password'),
    });

    if (error) {
      errorMsg = error.message;
      loading = false;
    } else {
      sent = true;
      loading = false;
    }
  }
</script>

<AuthShell backHref="/auth/signin" backLabel="Sign in">
  {#if sent}
    <div class="w-14 h-14 rounded-2xl bg-blue-dim border border-blue/20 text-blue flex items-center justify-center mb-8">
      <UiIcon name="mail" size={24} />
    </div>
    <h1 class="font-display text-[44px] leading-[1.05] text-text0 mb-3">Check your email</h1>
    <p class="text-[17px] text-text1 leading-relaxed mb-3">
      We sent a reset link to <span class="text-text0">{email}</span>. It expires in 1 hour.
    </p>
    <p class="text-[15px] text-text2 leading-relaxed mb-8">
      Didn't get it? Check your spam folder, or go back and try again.
    </p>
    <a
      href="/auth/signin"
      class="inline-flex items-center justify-center w-full h-14 rounded-[18px] border border-border text-text0 text-[16px] font-semibold no-underline hover:border-text2/60 transition-colors"
    >
      Back to sign in
    </a>
  {:else}
    <h1 class="font-display text-[44px] leading-[1.05] text-text0 mb-3">Forgot your password?</h1>
    <p class="text-[17px] text-text1 leading-relaxed mb-8">Enter your email and we'll send you a reset link.</p>

    {#if errorMsg}
      <FormAlert class="mb-6">{errorMsg}</FormAlert>
    {/if}

    <form onsubmit={handleReset} class="flex flex-col gap-6">
      <TextField
        id="email"
        label="Email"
        type="email"
        autocomplete="email"
        bind:value={email}
        required
        placeholder="athlete@example.com"
      />

      <Button type="submit" disabled={loading} class="mt-2">
        {loading ? 'Sending…' : 'Send reset link'}
      </Button>
    </form>
  {/if}
</AuthShell>
