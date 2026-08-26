<script lang="ts">
  import { supabase } from '$lib/supabase';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { authRedirectUrl } from '$lib/utils/redirectUrl';
  import { completeAuthSession } from '$lib/utils/completeAuthSession';
  import { goto } from '$app/navigation';
  import OtpCodeInput from '$lib/components/OtpCodeInput.svelte';

  let step = $state<'form' | 'verify'>('form');

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

<div class="min-h-full flex flex-col p-6 items-center justify-center relative">
  <!-- Decor elements -->
  <div class="absolute top-0 left-0 w-full h-[300px] bg-gradient-to-b from-[rgba(0,200,168,0.15)] to-transparent pointer-events-none"></div>
  <div class="absolute -top-[100px] -left-[100px] w-[300px] h-[300px] bg-blue rounded-full blur-[120px] opacity-20 pointer-events-none"></div>

  <div class="w-full max-w-sm z-10">
    {#if step === 'form'}
      <div class="mb-10 text-center">
        <h1 class="text-3xl font-bold tracking-tight mb-2">Join ASTRAPHE</h1>
        <p class="text-text2 text-sm">Create your AI-powered training hub</p>
      </div>

      {#if errorMsg}
        <div class="p-3 bg-red-dim border-l-2 border-red rounded-lg mb-6 text-xs text-text0 leading-relaxed">
          {errorMsg}
        </div>
      {/if}

      <form onsubmit={handleSignUp} class="flex flex-col gap-4">
        <div>
          <label for="name" class="block text-[10px] text-text2 font-mono uppercase tracking-widest mb-1.5 ml-1">Full Name</label>
          <input
            id="name"
            type="text"
            bind:value={name}
            required
            class="w-full px-4 py-3.5 bg-glass border border-border rounded-xl text-text0 text-sm outline-none focus:border-teal focus:bg-glass2 transition-colors placeholder:text-text2"
            placeholder="Marcus Aurelius"
          />
        </div>

        <div>
          <label for="email" class="block text-[10px] text-text2 font-mono uppercase tracking-widest mb-1.5 ml-1">Email</label>
          <input
            id="email"
            type="email"
            bind:value={email}
            required
            class="w-full px-4 py-3.5 bg-glass border border-border rounded-xl text-text0 text-sm outline-none focus:border-teal focus:bg-glass2 transition-colors placeholder:text-text2"
            placeholder="athlete@example.com"
          />
        </div>

        <div>
          <label for="password" class="block text-[10px] text-text2 font-mono uppercase tracking-widest mb-1.5 ml-1">Password</label>
          <input
            id="password"
            type="password"
            bind:value={password}
            required
            class="w-full px-4 py-3.5 bg-glass border border-border rounded-xl text-text0 text-sm outline-none focus:border-teal focus:bg-glass2 transition-colors placeholder:text-text2"
            placeholder="••••••••"
          />
        </div>

        <button
          type="submit"
          disabled={loading}
          class="w-full mt-4 py-3.5 bg-teal text-bg1 font-semibold rounded-xl hover:bg-teal/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? 'Creating Account...' : 'Create Account'}
        </button>
      </form>

      <p class="text-center text-xs text-text2 mt-8">
        Already have an account? <a href="/auth/signin" class="text-text0 hover:text-blue transition-colors">Sign in</a>
      </p>
    {:else}
      <div class="mb-10 text-center">
        <h1 class="text-3xl font-bold tracking-tight mb-2">Check your email</h1>
        <p class="text-text2 text-sm">We sent a confirmation link and a 6-digit code to {email}</p>
      </div>

      {#if verifyError}
        <div class="p-3 bg-red-dim border-l-2 border-red rounded-lg mb-6 text-xs text-text0 leading-relaxed">
          {verifyError}
        </div>
      {/if}

      {#if resendMsg}
        <div class="p-3 bg-glass border-l-2 border-teal rounded-lg mb-6 text-xs text-text0 leading-relaxed">
          {resendMsg}
        </div>
      {/if}

      <form onsubmit={handleVerifyCode} class="flex flex-col gap-4">
        <div>
          <label for="otp-code" class="block text-[10px] text-text2 font-mono uppercase tracking-widest mb-1.5 ml-1">Verification code</label>
          <OtpCodeInput bind:value={code} disabled={verifying} />
        </div>

        <button
          type="submit"
          disabled={verifying || code.length !== 6}
          class="w-full mt-4 py-3.5 bg-teal text-bg1 font-semibold rounded-xl hover:bg-teal/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {verifying ? 'Verifying...' : 'Verify'}
        </button>
      </form>

      <p class="text-center text-xs text-text2 mt-8">
        Didn't get a code?
        <button
          type="button"
          onclick={handleResend}
          disabled={resending}
          class="text-text0 hover:text-blue transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {resending ? 'Sending...' : 'Resend code'}
        </button>
      </p>
      <p class="text-center text-xs text-text2 mt-2">
        <button
          type="button"
          onclick={() => { step = 'form'; verifyError = ''; resendMsg = ''; }}
          class="text-text0 hover:text-blue transition-colors"
        >
          Back to sign up
        </button>
      </p>
    {/if}
  </div>
</div>
