import { describe, expect, it } from 'vitest';
import { firstName, isProfileComplete } from './profile';

const full = {
  sport_focus: ['bike'],
  measurement_units: 'metric',
  time_format: '24h',
  date_of_birth: '1990-01-01',
  gender: 'female',
  weight_kg: 60,
  height_cm: 170,
};

describe('isProfileComplete', () => {
  it('is true with every onboarding field', () => {
    expect(isProfileComplete(full)).toBe(true);
  });
  it('is false when any field is missing or blank', () => {
    expect(isProfileComplete(null)).toBe(false);
    expect(isProfileComplete({ ...full, gender: ' ' })).toBe(false);
    expect(isProfileComplete({ ...full, weight_kg: 0 })).toBe(false);
    expect(isProfileComplete({ ...full, sport_focus: [] })).toBe(false);
  });
});

describe('firstName', () => {
  it('takes the first word of the first non-empty candidate', () => {
    expect(firstName(undefined, '', 'Sean Balbale')).toBe('Sean');
    expect(firstName(null)).toBe('');
  });
});
