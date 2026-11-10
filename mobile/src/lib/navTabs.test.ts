import { describe, expect, it } from 'vitest';
import { activeTabFor, subtabsFor, titleFor } from './navTabs';

describe('navTabs', () => {
  it('maps grouped routes to their owning tab', () => {
    expect(activeTabFor('/')).toBe('/dashboard');
    expect(activeTabFor('/zones')).toBe('/training');
    expect(activeTabFor('/sleep')).toBe('/recovery');
    expect(activeTabFor('/strain')).toBe('/recovery');
    expect(activeTabFor('/chat')).toBe('/chat');
  });

  it('returns null for routes outside the tab bar', () => {
    expect(activeTabFor('/profile')).toBeNull();
    expect(activeTabFor('/profile/privacy')).toBeNull();
  });

  it('gives header titles, including Me for profile pages', () => {
    expect(titleFor('/dashboard')).toBe('Today');
    expect(titleFor('/zones')).toBe('Training');
    expect(titleFor('/sleep')).toBe('Body');
    expect(titleFor('/profile/connections')).toBe('Me');
  });

  it('only exposes sub-tabs for grouped tabs', () => {
    expect(subtabsFor('/training')?.map((t) => t.id)).toEqual(['/training', '/trends', '/zones']);
    expect(subtabsFor('/strain')?.map((t) => t.id)).toEqual(['/recovery', '/sleep', '/strain', '/heart-rate', '/weight']);
    expect(activeTabFor('/heart-rate')).toBe('/recovery');
    expect(activeTabFor('/weight')).toBe('/recovery');
    expect(subtabsFor('/dashboard')).toBeNull();
    expect(subtabsFor('/plan')).toBeNull();
  });
});
