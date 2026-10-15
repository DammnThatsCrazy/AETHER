// =============================================================================
// Aether SDK — FEEDBACK MODULE (React Native) — Thin Native Bridge
// Delegates all survey/feedback operations to NativeModules.AetherFeedback
// =============================================================================

import { NativeModules } from 'react-native';
import type { Survey, SurveyResponse, SurveyTrigger } from '@aether/shared/feedback-types';

export type { Survey, SurveyResponse, SurveyTrigger };

const { AetherFeedback } = NativeModules;

// ---------------------------------------------------------------------------
// Thin bridge — all logic lives in the native layer
// ---------------------------------------------------------------------------

class RNFeedbackModule {
  initialize(apiKey: string, endpoint: string): void {
    AetherFeedback?.initialize(apiKey, endpoint);
  }

  registerSurvey(survey: Survey, trigger?: SurveyTrigger): void {
    AetherFeedback?.registerSurvey(survey, trigger ?? {});
  }

  async shouldShowSurvey(surveyId: string): Promise<boolean> {
    return AetherFeedback?.shouldShowSurvey(surveyId) ?? false;
  }

  async recordSurveyShown(surveyId: string): Promise<void> {
    await AetherFeedback?.recordSurveyShown(surveyId);
  }

  async submitResponse(surveyId: string, responses: Record<string, unknown>): Promise<void> {
    await AetherFeedback?.submitResponse(surveyId, responses);
  }

  async dismissSurvey(surveyId: string): Promise<void> {
    await AetherFeedback?.dismissSurvey(surveyId);
  }

  async getSurveyResponses(surveyId?: string): Promise<SurveyResponse[]> {
    return AetherFeedback?.getSurveyResponses(surveyId ?? null) ?? [];
  }

  destroy(): void {
    AetherFeedback?.destroy();
  }
}

export const RNFeedback = new RNFeedbackModule();
export default RNFeedback;
