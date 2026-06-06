import { http, HttpResponse } from 'msw';

// Closed demo: synthetic ingestion endpoint so the SDK/no-SDK simulator works
// with no backend. Relative paths resolve to the dev server origin.
export const handlers = [
  http.post('/v1/batch', async () =>
    HttpResponse.json({
      data: { event_id: `demo_${Math.random().toString(36).slice(2, 10)}`, accepted: true },
      status: 'ok',
      timestamp: new Date().toISOString(),
    }),
  ),
];
