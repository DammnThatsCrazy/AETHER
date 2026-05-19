// =============================================================================
// Aether SDK — FEEDBACK MODULE (Android)
// In-app surveys: NPS, CSAT, CES, custom questions
// =============================================================================

package com.aether.sdk

import android.content.Context
import android.content.SharedPreferences
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.*
import java.util.concurrent.ConcurrentHashMap

// =============================================================================
// TYPES
// =============================================================================

enum class AetherSurveyType(val value: String) {
    NPS("nps"),
    CSAT("csat"),
    CES("ces"),
    CUSTOM("custom")
}

enum class AetherQuestionType(val value: String) {
    RATING("rating"),
    SCALE("scale"),
    TEXT("text"),
    MULTIPLE_CHOICE("multipleChoice"),
    BOOLEAN("boolean")
}

data class AetherSurveyQuestion(
    val id: String,
    val type: AetherQuestionType,
    val text: String,
    val options: List<String>? = null,
    val min: Int? = null,
    val max: Int? = null,
    val required: Boolean = true
) {
    fun toMap(): Map<String, Any?> = mapOf(
        "id" to id,
        "type" to type.value,
        "text" to text,
        "options" to options,
        "min" to min,
        "max" to max,
        "required" to required
    )

    fun toJSONObject(): JSONObject {
        val obj = JSONObject()
        obj.put("id", id)
        obj.put("type", type.value)
        obj.put("text", text)
        options?.let { obj.put("options", JSONArray(it)) }
        min?.let { obj.put("min", it) }
        max?.let { obj.put("max", it) }
        obj.put("required", required)
        return obj
    }
}

data class AetherSurvey(
    val id: String,
    val type: AetherSurveyType,
    val title: String,
    val questions: List<AetherSurveyQuestion>,
    val thankYouMessage: String? = null
) {
    fun toJSONObject(): JSONObject {
        val obj = JSONObject()
        obj.put("id", id)
        obj.put("type", type.value)
        obj.put("title", title)
        obj.put("questions", JSONArray(questions.map { it.toJSONObject() }))
        thankYouMessage?.let { obj.put("thankYouMessage", it) }
        return obj
    }
}

data class AetherSurveyTrigger(
    val event: String? = null,
    val delayMs: Long? = null,
    val screenName: String? = null,
    val sessionCount: Int? = null,
    val sampleRate: Double? = null,
    val maxDisplays: Int? = null
)

data class AetherSurveyResponse(
    val surveyId: String,
    val responses: Map<String, Any?>,
    val completedAt: String,
    val dismissed: Boolean
) {
    fun toJSONObject(): JSONObject {
        val obj = JSONObject()
        obj.put("surveyId", surveyId)
        obj.put("responses", JSONObject(responses.mapValues { it.value ?: JSONObject.NULL }))
        obj.put("completedAt", completedAt)
        obj.put("dismissed", dismissed)
        return obj
    }
}

// =============================================================================
// FEEDBACK MODULE
// =============================================================================

object AetherFeedback {
    private const val PREFS_NAME = "com.aether.sdk.feedback"
    private const val RESPONSES_KEY = "aether_survey_responses"
    private const val DISPLAY_COUNT_PREFIX = "aether_survey_display_"

    private var prefs: SharedPreferences? = null
    private val dateFormat = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US).apply {
        timeZone = TimeZone.getTimeZone("UTC")
    }

    /** Registered surveys keyed by ID. */
    private val surveys = ConcurrentHashMap<String, AetherSurvey>()
    /** Triggers keyed by survey ID. */
    private val triggers = ConcurrentHashMap<String, AetherSurveyTrigger>()
    /** Cached survey responses. */
    private val storedResponses = Collections.synchronizedList(mutableListOf<AetherSurveyResponse>())

    /**
     * Initialize the feedback module. Call once from Application.onCreate().
     */
    fun initialize(context: Context) {
        prefs = context.applicationContext
            .getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        loadResponses()
    }

    // =========================================================================
    // STATIC SURVEY BUILDERS
    // =========================================================================

    /** Create a standard NPS (Net Promoter Score) survey. */
    fun createNPS(
        id: String = "nps_default",
        title: String = "How likely are you to recommend us?"
    ): AetherSurvey = AetherSurvey(
        id = id,
        type = AetherSurveyType.NPS,
        title = title,
        questions = listOf(
            AetherSurveyQuestion(
                id = "nps_score",
                type = AetherQuestionType.SCALE,
                text = "On a scale of 0-10, how likely are you to recommend us to a friend or colleague?",
                min = 0,
                max = 10,
                required = true
            ),
            AetherSurveyQuestion(
                id = "nps_reason",
                type = AetherQuestionType.TEXT,
                text = "What is the primary reason for your score?",
                required = false
            )
        ),
        thankYouMessage = "Thank you for your feedback!"
    )

    /** Create a standard CSAT (Customer Satisfaction) survey. */
    fun createCSAT(
        id: String = "csat_default",
        title: String = "How satisfied are you?"
    ): AetherSurvey = AetherSurvey(
        id = id,
        type = AetherSurveyType.CSAT,
        title = title,
        questions = listOf(
            AetherSurveyQuestion(
                id = "csat_score",
                type = AetherQuestionType.RATING,
                text = "How satisfied are you with your experience?",
                min = 1,
                max = 5,
                required = true
            ),
            AetherSurveyQuestion(
                id = "csat_comment",
                type = AetherQuestionType.TEXT,
                text = "Any additional comments?",
                required = false
            )
        ),
        thankYouMessage = "Thank you for rating your experience!"
    )

    /** Create a standard CES (Customer Effort Score) survey. */
    fun createCES(
        id: String = "ces_default",
        title: String = "How easy was it?"
    ): AetherSurvey = AetherSurvey(
        id = id,
        type = AetherSurveyType.CES,
        title = title,
        questions = listOf(
            AetherSurveyQuestion(
                id = "ces_score",
                type = AetherQuestionType.SCALE,
                text = "How easy was it to accomplish what you wanted to do?",
                min = 1,
                max = 7,
                required = true
            ),
            AetherSurveyQuestion(
                id = "ces_feedback",
                type = AetherQuestionType.TEXT,
                text = "What could we do to make it easier?",
                required = false
            )
        ),
        thankYouMessage = "Thank you! Your feedback helps us improve."
    )

    // =========================================================================
    // SURVEY REGISTRATION
    // =========================================================================

    /** Register a survey for later display, optionally with a trigger configuration. */
    fun registerSurvey(survey: AetherSurvey, trigger: AetherSurveyTrigger? = null) {
        surveys[survey.id] = survey
        trigger?.let { triggers[survey.id] = it }
    }

    // =========================================================================
    // SURVEY DISPLAY
    // =========================================================================

    /**
     * Programmatically show a survey. Emits a `survey_shown` event.
     * Note: Actual UI rendering is the host app's responsibility.
     */
    fun showSurvey(surveyId: String) {
        val survey = surveys[surveyId] ?: return

        // Increment display count
        val countKey = DISPLAY_COUNT_PREFIX + surveyId
        val currentCount = prefs?.getInt(countKey, 0) ?: 0
        prefs?.edit()?.putInt(countKey, currentCount + 1)?.apply()

        Aether.track("survey_shown", mapOf(
            "survey_id" to surveyId,
            "survey_type" to survey.type.value,
            "title" to survey.title,
            "question_count" to survey.questions.size,
            "display_count" to currentCount + 1
        ))
    }

    /** Evaluate whether a survey should be shown based on its trigger rules. */
    fun shouldShowSurvey(surveyId: String): Boolean {
        if (!surveys.containsKey(surveyId)) return false
        val trigger = triggers[surveyId] ?: return true

        // Check sample rate
        trigger.sampleRate?.let { rate ->
            if (rate < 1.0 && Math.random() > rate) return false
        }

        // Check max displays
        trigger.maxDisplays?.let { max ->
            val countKey = DISPLAY_COUNT_PREFIX + surveyId
            val currentCount = prefs?.getInt(countKey, 0) ?: 0
            if (currentCount >= max) return false
        }

        return true
    }

    // =========================================================================
    // RESPONSE HANDLING
    // =========================================================================

    /** Record survey responses. Tracks `survey_completed` event. */
    fun submitResponse(surveyId: String, responses: Map<String, Any?>) {
        val response = AetherSurveyResponse(
            surveyId = surveyId,
            responses = responses,
            completedAt = dateFormat.format(Date()),
            dismissed = false
        )

        storedResponses.add(response)
        persistResponses()

        val props = mutableMapOf<String, Any?>(
            "survey_id" to surveyId,
            "response_count" to responses.size,
            "responses" to responses
        )
        surveys[surveyId]?.let { props["survey_type"] = it.type.value }

        Aether.track("survey_completed", props)
    }

    /** Record a survey dismissal. Tracks `survey_dismissed` event. */
    fun dismissSurvey(surveyId: String) {
        val response = AetherSurveyResponse(
            surveyId = surveyId,
            responses = emptyMap(),
            completedAt = dateFormat.format(Date()),
            dismissed = true
        )

        storedResponses.add(response)
        persistResponses()

        val props = mutableMapOf<String, Any?>("survey_id" to surveyId)
        surveys[surveyId]?.let { props["survey_type"] = it.type.value }

        Aether.track("survey_dismissed", props)
    }

    /** Retrieve stored survey responses, optionally filtered by survey ID. */
    fun getSurveyResponses(surveyId: String? = null): List<AetherSurveyResponse> {
        return synchronized(storedResponses) {
            if (surveyId != null) {
                storedResponses.filter { it.surveyId == surveyId }
            } else {
                storedResponses.toList()
            }
        }
    }

    // =========================================================================
    // PERSISTENCE
    // =========================================================================

    private fun persistResponses() {
        val array = JSONArray()
        synchronized(storedResponses) {
            for (response in storedResponses) {
                array.put(response.toJSONObject())
            }
        }
        prefs?.edit()?.putString(RESPONSES_KEY, array.toString())?.apply()
    }

    private fun loadResponses() {
        val raw = prefs?.getString(RESPONSES_KEY, null) ?: return
        try {
            val array = JSONArray(raw)
            for (i in 0 until array.length()) {
                val obj = array.getJSONObject(i)
                val responsesObj = obj.optJSONObject("responses") ?: JSONObject()
                val responsesMap = mutableMapOf<String, Any?>()
                responsesObj.keys().forEach { key ->
                    responsesMap[key] = responsesObj.opt(key)
                }

                storedResponses.add(
                    AetherSurveyResponse(
                        surveyId = obj.getString("surveyId"),
                        responses = responsesMap,
                        completedAt = obj.getString("completedAt"),
                        dismissed = obj.getBoolean("dismissed")
                    )
                )
            }
        } catch (_: Exception) {
            // Corrupted cache — start fresh
            storedResponses.clear()
        }
    }
}
