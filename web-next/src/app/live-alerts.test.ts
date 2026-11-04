import {describe, expect, it} from 'vitest';
import {mergeAlert, visibleAlerts, type LiveAlert} from './live-alerts';

const row = (over: Partial<LiveAlert>): LiveAlert => ({id: 'e1', camera_id: 'porch', camera_name: 'Porch', kind: 'person', started_at: '2026-11-03T23:00:00Z', ended_at: null, open: true, ...over});

describe('live alerts', () => {
  it('upserts by id so an alert that closes does not add a second card', () => {
    const list = mergeAlert(mergeAlert([], row({})), row({ended_at: '2026-11-03T23:00:08Z', open: false}));
    expect(list).toHaveLength(1);
    expect(list[0].open).toBe(false);
  });
  it('keeps the newest first', () => {
    const list = mergeAlert(mergeAlert([], row({})), row({id: 'e2', camera_id: 'doorbell', started_at: '2026-11-03T23:00:05Z'}));
    expect(list.map(a => a.id)).toEqual(['e2', 'e1']);
  });
  it('shows open alerts and recently closed ones only', () => {
    const now = Date.parse('2026-11-03T23:01:00Z');
    const list = [row({id: 'open'}), row({id: 'recent', open: false, ended_at: '2026-11-03T23:00:55Z'}), row({id: 'old', open: false, ended_at: '2026-11-03T22:50:00Z'})];
    expect(visibleAlerts(list, now).map(a => a.id)).toEqual(['open', 'recent']);
  });
});
