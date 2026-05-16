import { Capacitor } from '@capacitor/core';
import { Health } from '@interval-health/capacitor-health';
import { api } from '../api';

export class HealthIntegration {
  static isAvailable(): boolean {
    return Capacitor.isNativePlatform();
  }

  static async requestPermissions(): Promise<boolean> {
    if (!this.isAvailable()) {
      console.warn('HealthKit is not available on the web. Simulating success.');
      return true; // Simulate success on web for dev
    }

    try {
      await Health.requestAuthorization({
        read: ['sleep', 'heartRate', 'workout'],
        write: []
      });
      return true;
    } catch (e) {
      console.error('Failed to request Health permissions:', e);
      return false;
    }
  }

  static async syncRecentData() {
    if (!this.isAvailable()) {
      console.log('Simulating Health sync on the web.');
      // Simulate API POST payload for backend
      await api.post('/v1/biometrics/sync', { status: 'mock_synced' });
      return;
    }

    try {
      const endDate = new Date();
      const startDate = new Date();
      startDate.setDate(endDate.getDate() - 7); // Last 7 days

      // Typically you would fetch actual data here using Health.query()
      // For scaffold:
      /*
      const hrv = await Health.query({
        sampleType: 'heartRateVariabilitySDNN',
        startDate: startDate.toISOString(),
        endDate: endDate.toISOString()
      });
      */
      
      const payload = {
        synced_at: new Date().toISOString(),
        device: Capacitor.getPlatform(),
        data: [] // mock empty array until fully wired
      };

      await api.post('/v1/biometrics/sync', payload);
      
      return payload;
    } catch (e) {
      console.error('Failed to sync Health data:', e);
      throw e;
    }
  }
}
