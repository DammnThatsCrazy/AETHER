import { Link } from 'react-router-dom';
import { Button } from '@aether/ui';
import { usePageMeta } from '@aether-marketing/lib/meta';

export function NotFoundPage() {
  usePageMeta({ title: 'Page not found — Aether by Olympus Labs' });
  return (
    <div className="mkt-container py-24 md:py-32">
      <h1 className="mkt-display">Page not found</h1>
      <p className="mkt-lead mt-4 max-w-xl">
        The page you are looking for does not exist or has moved.
      </p>
      <div className="mt-8 flex flex-wrap gap-4">
        <Button asChild variant="primary">
          <Link to="/">Back to the Aether home page</Link>
        </Button>
        <Button asChild variant="secondary">
          <Link to="/platform">Explore the platform</Link>
        </Button>
      </div>
    </div>
  );
}
