import { z } from 'zod';
import { restClient } from './rest/client';

// Placeholder customer-facing API stubs.
// Implement these as customer features are built out.

const profileSchema = z.object({
  id: z.string(),
  email: z.string(),
  displayName: z.string(),
});

export type Profile = z.infer<typeof profileSchema>;

export const api = {
  profile: {
    me: () => restClient.get('/v1/profile/me', profileSchema),
  },
};
