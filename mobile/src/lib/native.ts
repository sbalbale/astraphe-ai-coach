import { App } from '@capacitor/app';
import { Preferences } from '@capacitor/preferences';
import { BackgroundRunner } from '@capacitor/background-runner';

export async function setupNativeIntegrations() {
  // Setup Deep Links
  App.addListener('appUrlOpen', data => {
    console.log('App opened with URL:', data.url);
    if (data.url.includes('astraphe://connected')) {
      // Handle OAuth handshake return
      // For instance: goto('/connect?success=true')
    }
  });

  // Schedule Background Task
  try {
    await BackgroundRunner.requestPermissions({
      apis: ['geolocation', 'notifications']
    });

    await BackgroundRunner.dispatchEvent({
      label: 'com.astraphe.coach.syncHealthKit',
      event: 'sync',
      details: {}
    });
  } catch (e) {
    console.log('Background runner not supported or permissions denied', e);
  }
}

export async function cacheData(key: string, data: any) {
  await Preferences.set({
    key,
    value: JSON.stringify(data)
  });
}

export async function getCachedData(key: string) {
  const { value } = await Preferences.get({ key });
  return value ? JSON.parse(value) : null;
}
