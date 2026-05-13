// =============================================================================
// Aether SDK — FEEDBACK MODULE (iOS)
// In-app surveys: NPS, CSAT, CES, custom questions
// =============================================================================

import Foundation

// MARK: - Types

public enum AetherSurveyType: String, Codable {
    case nps
    case csat
    case ces
    case custom
}

public enum AetherQuestionType: String, Codable {
    case rating
    case scale
    case text
    case multipleChoice
    case boolean
}

public struct AetherSurveyQuestion: Codable {
    public let id: String
    public let type: AetherQuestionType
    public let text: String
    public var options: [String]?
    public var min: Int?
    public var max: Int?
    public var required: Bool

    public init(
        id: String,
        type: AetherQuestionType,
        text: String,
        options: [String]? = nil,
        min: Int? = nil,
        max: Int? = nil,
        required: Bool = true
    ) {
        self.id = id
        self.type = type
        self.text = text
        self.options = options
        self.min = min
        self.max = max
        self.required = required
    }
}

public struct AetherSurvey: Codable {
    public let id: String
    public let type: AetherSurveyType
    public let title: String
    public let questions: [AetherSurveyQuestion]
    public var thankYouMessage: String?

    public init(
        id: String,
        type: AetherSurveyType,
        title: String,
        questions: [AetherSurveyQuestion],
        thankYouMessage: String? = nil
    ) {
        self.id = id
        self.type = type
        self.title = title
        self.questions = questions
        self.thankYouMessage = thankYouMessage
    }
}

public struct AetherSurveyTrigger: Codable {
    public var event: String?
    public var delay: TimeInterval?
    public var screenName: String?
    public var sessionCount: Int?
    public var sampleRate: Double?
    public var maxDisplays: Int?

    public init(
        event: String? = nil,
        delay: TimeInterval? = nil,
        screenName: String? = nil,
        sessionCount: Int? = nil,
        sampleRate: Double? = nil,
        maxDisplays: Int? = nil
    ) {
        self.event = event
        self.delay = delay
        self.screenName = screenName
        self.sessionCount = sessionCount
        self.sampleRate = sampleRate
        self.maxDisplays = maxDisplays
    }
}

public struct AetherSurveyResponse: Codable {
    public let surveyId: String
    public let responses: [String: AnyCodable]
    public let completedAt: String
    public let dismissed: Bool

    public init(
        surveyId: String,
        responses: [String: AnyCodable],
        completedAt: String,
        dismissed: Bool
    ) {
        self.surveyId = surveyId
        self.responses = responses
        self.completedAt = completedAt
        self.dismissed = dismissed
    }
}

// MARK: - AetherFeedback

public final class AetherFeedback {
    public static let shared = AetherFeedback()

    private let serialQueue = DispatchQueue(label: "com.aether.sdk.feedback")
    private let defaults = UserDefaults(suiteName: "com.aether.sdk")!

    private let responsesKey = "aether_survey_responses"
    private let displayCountPrefix = "aether_survey_display_"

    /// Registered surveys keyed by ID.
    private var surveys: [String: AetherSurvey] = [:]
    /// Triggers keyed by survey ID.
    private var triggers: [String: AetherSurveyTrigger] = [:]
    /// Cached survey responses.
    private var storedResponses: [AetherSurveyResponse] = []

    private init() {
        loadResponses()
    }

    // MARK: - Static Survey Builders

    /// Create a standard NPS (Net Promoter Score) survey.
    public static func createNPS(id: String = "nps_default", title: String = "How likely are you to recommend us?") -> AetherSurvey {
        return AetherSurvey(
            id: id,
            type: .nps,
            title: title,
            questions: [
                AetherSurveyQuestion(
                    id: "nps_score",
                    type: .scale,
                    text: "On a scale of 0-10, how likely are you to recommend us to a friend or colleague?",
                    min: 0,
                    max: 10,
                    required: true
                ),
                AetherSurveyQuestion(
                    id: "nps_reason",
                    type: .text,
                    text: "What is the primary reason for your score?",
                    required: false
                )
            ],
            thankYouMessage: "Thank you for your feedback!"
        )
    }

    /// Create a standard CSAT (Customer Satisfaction) survey.
    public static func createCSAT(id: String = "csat_default", title: String = "How satisfied are you?") -> AetherSurvey {
        return AetherSurvey(
            id: id,
            type: .csat,
            title: title,
            questions: [
                AetherSurveyQuestion(
                    id: "csat_score",
                    type: .rating,
                    text: "How satisfied are you with your experience?",
                    min: 1,
                    max: 5,
                    required: true
                ),
                AetherSurveyQuestion(
                    id: "csat_comment",
                    type: .text,
                    text: "Any additional comments?",
                    required: false
                )
            ],
            thankYouMessage: "Thank you for rating your experience!"
        )
    }

    /// Create a standard CES (Customer Effort Score) survey.
    public static func createCES(id: String = "ces_default", title: String = "How easy was it?") -> AetherSurvey {
        return AetherSurvey(
            id: id,
            type: .ces,
            title: title,
            questions: [
                AetherSurveyQuestion(
                    id: "ces_score",
                    type: .scale,
                    text: "How easy was it to accomplish what you wanted to do?",
                    min: 1,
                    max: 7,
                    required: true
                ),
                AetherSurveyQuestion(
                    id: "ces_feedback",
                    type: .text,
                    text: "What could we do to make it easier?",
                    required: false
                )
            ],
            thankYouMessage: "Thank you! Your feedback helps us improve."
        )
    }

    // MARK: - Survey Registration

    /// Register a survey for later display, optionally with a trigger configuration.
    public func registerSurvey(_ survey: AetherSurvey, trigger: AetherSurveyTrigger? = nil) {
        serialQueue.async { [weak self] in
            self?.surveys[survey.id] = survey
            if let trigger = trigger {
                self?.triggers[survey.id] = trigger
            }
        }
    }

    // MARK: - Survey Display

    /// Programmatically show a survey. Emits a `survey_shown` event.
    /// Note: Actual UI rendering is the host app's responsibility.
    /// The app should listen for the event and display the appropriate UI.
    public func showSurvey(_ surveyId: String) {
        serialQueue.async { [weak self] in
            guard let self = self else { return }
            guard let survey = self.surveys[surveyId] else { return }

            // Increment display count
            let countKey = self.displayCountPrefix + surveyId
            let currentCount = self.defaults.integer(forKey: countKey)
            self.defaults.set(currentCount + 1, forKey: countKey)

            Aether.shared.track("survey_shown", properties: [
                "survey_id": AnyCodable(surveyId),
                "survey_type": AnyCodable(survey.type.rawValue),
                "title": AnyCodable(survey.title),
                "question_count": AnyCodable(survey.questions.count),
                "display_count": AnyCodable(currentCount + 1)
            ])
        }
    }

    /// Evaluate whether a survey should be shown based on its trigger rules.
    public func shouldShowSurvey(_ surveyId: String) -> Bool {
        return serialQueue.sync {
            guard surveys[surveyId] != nil else { return false }
            guard let trigger = triggers[surveyId] else { return true }

            // Check sample rate
            if let sampleRate = trigger.sampleRate, sampleRate < 1.0 {
                if Double.random(in: 0.0..<1.0) > sampleRate {
                    return false
                }
            }

            // Check max displays
            if let maxDisplays = trigger.maxDisplays {
                let countKey = displayCountPrefix + surveyId
                let currentCount = defaults.integer(forKey: countKey)
                if currentCount >= maxDisplays {
                    return false
                }
            }

            return true
        }
    }

    // MARK: - Response Handling

    /// Record survey responses. Tracks `survey_completed` event.
    public func submitResponse(_ surveyId: String, responses: [String: AnyCodable]) {
        let response = AetherSurveyResponse(
            surveyId: surveyId,
            responses: responses,
            completedAt: ISO8601DateFormatter().string(from: Date()),
            dismissed: false
        )

        serialQueue.async { [weak self] in
            self?.storedResponses.append(response)
            self?.persistResponses()
        }

        var props: [String: AnyCodable] = [
            "survey_id": AnyCodable(surveyId),
            "response_count": AnyCodable(responses.count)
        ]
        if let survey = serialQueue.sync(execute: { surveys[surveyId] }) {
            props["survey_type"] = AnyCodable(survey.type.rawValue)
        }
        // Include actual responses in tracking
        props["responses"] = AnyCodable(responses.mapValues { $0.value })

        Aether.shared.track("survey_completed", properties: props)
    }

    /// Record a survey dismissal. Tracks `survey_dismissed` event.
    public func dismissSurvey(_ surveyId: String) {
        let response = AetherSurveyResponse(
            surveyId: surveyId,
            responses: [:],
            completedAt: ISO8601DateFormatter().string(from: Date()),
            dismissed: true
        )

        serialQueue.async { [weak self] in
            self?.storedResponses.append(response)
            self?.persistResponses()
        }

        var props: [String: AnyCodable] = [
            "survey_id": AnyCodable(surveyId)
        ]
        if let survey = serialQueue.sync(execute: { surveys[surveyId] }) {
            props["survey_type"] = AnyCodable(survey.type.rawValue)
        }

        Aether.shared.track("survey_dismissed", properties: props)
    }

    /// Retrieve stored survey responses, optionally filtered by survey ID.
    public func getSurveyResponses(surveyId: String? = nil) -> [AetherSurveyResponse] {
        return serialQueue.sync {
            if let surveyId = surveyId {
                return storedResponses.filter { $0.surveyId == surveyId }
            }
            return storedResponses
        }
    }

    // MARK: - Persistence

    private func persistResponses() {
        guard let data = try? JSONEncoder().encode(storedResponses) else { return }
        defaults.set(data, forKey: responsesKey)
    }

    private func loadResponses() {
        guard let data = defaults.data(forKey: responsesKey),
              let responses = try? JSONDecoder().decode([AetherSurveyResponse].self, from: data) else { return }
        storedResponses = responses
    }
}
