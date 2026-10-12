const STATUS_CLASSES = new Set(['successful', 'denied', 'blocked', 'degraded', 'failed']);

const REFERENCE_FIELDS = [
  'batch_id', 'batchId', 'receipt_id', 'receiptId', 'receipt_ref', 'receiptRef',
  'consent_receipt_ids', 'consentReceiptIds',
  'session_id', 'sessionId',
  'decision_id', 'decisionId', 'decision_ref', 'decisionRef', 'rights_decision_ref',
  'task_id', 'taskId', 'result_id', 'resultId', 'export_id', 'exportId',
  'approval_id', 'approvalId', 'usage_event_id', 'usageEventId',
  'usage_evidence_id', 'usageEvidenceId', 'audit_id', 'auditId',
  'audit_event_id', 'auditEventId',
];

function classifyStatus({ operation, httpStatus, responseOk, contractError, data }) {
  if (httpStatus === 401 || httpStatus === 403) return 'denied';
  if (httpStatus === 423 || httpStatus === 429) return 'blocked';
  if (contractError) return 'failed';
  if (httpStatus === 206 || httpStatus === 207) return 'degraded';
  if (!responseOk) return 'failed';
  if (operation === 'observe' && Number.isInteger(data?.rejected) && data.rejected > 0) {
    return 'degraded';
  }
  return 'successful';
}

function extractReferences(data) {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return {};
  const references = {};
  for (const field of REFERENCE_FIELDS) {
    const value = data[field];
    if (typeof value === 'string' && value.length > 0 && value.length <= 256) {
      references[field] = value;
    } else if (
      (field === 'consent_receipt_ids' || field === 'consentReceiptIds')
      && Array.isArray(value)
      && value.length > 0
      && value.length <= 100
      && value.every((item) => typeof item === 'string' && item.length > 0 && item.length <= 256)
    ) {
      references[field] = [...value];
    }
  }
  return references;
}

export function normalizeInteractionOutcome({
  operation,
  httpStatus = null,
  requestId,
  apiRequestId,
  responseOk = false,
  contractError = false,
  code,
  data,
}) {
  if (!['query', 'observe', 'auth'].includes(operation)) {
    throw new Error('Interaction operation must be query, observe, or auth.');
  }
  if (typeof requestId !== 'string' || !requestId) {
    throw new Error('Interaction request ID is required.');
  }

  const statusClass = classifyStatus({ operation, httpStatus, responseOk, contractError, data });
  if (!STATUS_CLASSES.has(statusClass)) throw new Error('Unsupported interaction status class.');
  return {
    version: '1',
    operation,
    status_class: statusClass,
    request_id: requestId,
    ...(typeof apiRequestId === 'string' && apiRequestId ? { api_request_id: apiRequestId } : {}),
    http_status: Number.isInteger(httpStatus) ? httpStatus : null,
    ...(typeof code === 'string' && code ? { error_code: code } : {}),
    references: extractReferences(data),
  };
}

export const interactionStatusClasses = Object.freeze([...STATUS_CLASSES]);
