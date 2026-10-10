import { Profile360View } from '@kyber/components/profile360';

interface Entity360PageProps {
  readonly entityId: string;
  readonly onBack: () => void;
}

export function Entity360Page({ entityId, onBack }: Entity360PageProps) {
  return <Profile360View type="human" id={entityId} onBack={onBack} />;
}
