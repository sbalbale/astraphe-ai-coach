<script lang="ts">
  import { MIN_PASSWORD_LENGTH } from '$lib/utils/passwordStrength';
  import { supabase } from '$lib/supabase';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { authRedirectUrl } from '$lib/utils/redirectUrl';
  import { completeAuthSession } from '$lib/utils/completeAuthSession';
  import { goto } from '$app/navigation';
  import OtpCodeInput from '$lib/components/OtpCodeInput.svelte';
  import AuthShell from '$lib/components/ui/AuthShell.svelte';
  import TextField from '$lib/components/ui/TextField.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import FormAlert from '$lib/components/ui/FormAlert.svelte';
  import UiIcon from '$lib/components/ui/UiIcon.svelte';
  import PasswordStrengthMeter from '$lib/components/ui/PasswordStrengthMeter.svelte';

  // Mirrors [auth] minimum_password_length in supabase/config.toml (the server enforces it).  let step = $state<'form' | 'verify'>('form');

  let name = $state('');
  let email = $state('');
  let password = $state('');
  let loading = $state(false);
  let errorMsg = $state('');

  let code = $state('');
  let verifying = $state(false);
  let verifyError = $state('');
  let resendMsg = $state('');
  let resending = $state(false);

  async function handleSignUp(e: Event) {
    e.preventDefault();
    loading = true;
    errorMsg = '';

    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        data: {
          full_name: name,
        },
        emailRedirectTo: authRedirectUrl('callback'),
      }
    });

    if (error) {
      errorMsg = error.message;
      loading = false;
      return;
    }

    if (data.session) {
      authStore.applySession(data.session);
      await goto('/onboarding', { replaceState: true });
    } else {
      // Email confirmation required — Supabase sent the confirmation email
      loading = false;
      step = 'verify';
    }
  }

  async function handleVerifyCode(e: Event) {
    e.preventDefault();
    verifying = true;
    verifyError = '';

    const { data, error } = await supabase.auth.verifyOtp({
      email,
      token: code,
      type: 'signup',
    });

    if (error) {
      verifyError = error.message;
      verifying = false;
      return;
    }

    if (data.session) {
      await completeAuthSession(data.session);
    } else {
      verifying = false;
    }
  }

  async function handleResend() {
    resending = true;
    resendMsg = '';
    verifyError = '';

    const { error } = await supabase.auth.resend({ type: 'signup', email });

    resending = false;
    if (error) {
      verifyError = error.message;
    } else {
      resendMsg = 'Code resent — check your email.';
    }
  }
</script>

{#if step === 'form'}
  <AuthShell brand title="Train smarter." subtitle="Create your AI-powered training hub.">
    {#if errorMsg}
      <FormAlert class="mb-6">{errorMsg}</FormAlert>
    {/if}

    <form onsubmit={handleSignUp} class="flex flex-col gap-6">
      <TextField
        id="name"
        label="Full name"
        type="text"
        autocomplete="name"
        bind:value={name}
        required
        placeholder="Your name"
      />

      <TextField
        id="email"
        label="Email"
        type="email"
        autocomplete="email"
        bind:value={email}
        required
        placeholder="athlete@example.com"
      />

      <div>
        <TextField
          id="password"
          label="Password"
          type="password"
          autocomplete="new-password"
          bind:value={password}
          required
          minlength={MIN_PASSWORD_LENGTH}
          aria-describedby="password-strength"
          placeholder={`At least ${MIN_PASSWORD_LENGTH} characters`}
        />
        <PasswordStrengthMeter id="password-strength" {password} minLength={MIN_PASSWORD_LENGTH} />
      </div>

      <Button type="submit" disabled={loading} class="mt-2">
        {loading ? 'Creating account…' : 'Create account'}
      </Button>
    </form>

    {#snippet footer()}
      <p class="text-[16px] text-text2">
        Already training with us? <a href="/auth/signin" class="text-text0 font-medium no-underline hover:text-blue">Sign in</a>
      </p>
    {/snippet}
  </AuthShell>
{:else}
  <AuthShell onBack={() => { step = 'form'; verifyError = ''; resendMsg = ''; }} backLabel="Back">
    <div class="w-14 h-14 rounded-2xl bg-blue-dim border border-blue/20 text-blue flex items-center justify-center mb-8">
      <UiIcon name="mail" size={24} />
    </div>
    <h1 class="font-display text-[44px] leading-[1.05] text-text0 mb-3">Check your email</h1>
    <p class="text-[17px] text-text1 leading-relaxed mb-8">
      We sent a 6-digit code and a confirmation link to <span class="text-text0">{email}</span>. Enter the code below to verify your account.
    </p>

    {#if verifyError}
      <FormAlert class="mb-6">{verifyError}</FormAlert>
    {/if}

    {#if resendMsg}
      <FormAlert tone="success" class="mb-6">{resendMsg}</FormAlert>
    {/if}

    <form onsubmit={handleVerifyCode} class="flex flex-col gap-6">
      <div>
        <label for="otp-code" class="sr-only">Verification code</label>
        <OtpCodeInput bind:value={code} disabled={verifying} />
      </div>

      <Button type="submit" disabled={verifying || code.length !== 6}>
        {verifying ? 'Verifying…' : 'Verify'}
      </Button>
    </form>

    <p class="text-center text-[16px] text-text2 mt-8">
      Didn't get it?
      <button
        type="button"
        onclick={handleResend}
        disabled={resending}
        class="ml-1 bg-transparent border-none p-0 text-text0 font-medium cursor-pointer hover:text-blue disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {resending ? 'Sending…' : 'Resend code'}
      </button>
    </p>
  </AuthShell>
{/if}
