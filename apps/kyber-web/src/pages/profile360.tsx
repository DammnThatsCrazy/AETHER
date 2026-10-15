import { useParams } from 'react-router-dom';
import { PageWrapper } from '@kyber/components/layout';
import { Profile360View } from '@kyber/components/profile360';
import type { Profile360EntityType } from '@kyber/types';

export function Profile360Page() {
  const { type = 'human', id = '' } = useParams<{ type?: string; id?: string }>();

  return (
    <PageWrapper title="Profile 360">
      <Profile360View type={type as Profile360EntityType} id={id} />
    </PageWrapper>
  );
}
