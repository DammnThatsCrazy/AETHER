// =============================================================================
// Aether DATA LAKE — STREAMING MODULE
// =============================================================================

export {
  StreamingBridge,
  type StreamingBridgeConfig,
  type KafkaConsumerAdapter,
  type KafkaMessage,
  type ClickHouseWriter,
  type StreamingMetrics,
  type ConsumerStatus,
} from './streaming-bridge.js';

export {
  BackfillManager,
  type BackfillJob,
  type BackfillScope,
  type BackfillPriority,
  type BackfillCheckpoint,
  type PartitionTask,
  type BackfillPipelineExecutor,
} from './backfill-manager.js';
