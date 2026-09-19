import { LaunchPackPage } from '../../../marketing/src/LaunchPackPage';
import { getLaunchPackPage } from '../../../marketing/src/content-loader';
import { usePageMeta } from '@aether-marketing/lib/meta';
import { WaitlistSection } from '@aether-marketing/components/waitlist-section';

export function ContactPage() {
  const page = getLaunchPackPage('Aether', '/contact');

  usePageMeta({
    title: page?.seoTitle ?? 'Contact — Aether',
    description:
      page?.seoDescription ??
      'Reach the Aether team — product questions, pilot conversations, partnership inquiries, and technical support.',
  });

  if (page === undefined) {
    return (
      <>
        <section className="mkt-container py-24">
          <p className="mkt-eyebrow">Contact</p>
          <h1 className="mkt-display mt-3">Talk to the Aether team.</h1>
          <p className="mkt-lead mt-4 max-w-2xl">
            Product questions, pilot conversations, partnership inquiries, and
            technical support — reach us directly.
          </p>
        </section>
        <WaitlistSection
          variant="early-access"
          eyebrow="Get in touch"
          title="Start a conversation"
          body="Tell us what you're working on and we'll connect you with the right person on the Aether team."
        />
      </>
    );
  }

  return <LaunchPackPage page={page} />;
}
