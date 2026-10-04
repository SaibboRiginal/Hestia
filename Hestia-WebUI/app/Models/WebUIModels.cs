namespace Hestia.WebUI.Models;

using System.Text.Json.Serialization;

// ── Auth ────────────────────────────────────────────────────────────────

public record LoginRequest(string Token);

public record LoginResponse(string Status, int ExpiresInSeconds);

public record TokenStatusResponse(
    bool Active,
    DateTime? CreatedAt,
    DateTime? ExpiresAt,
    int RemainingSeconds,
    double RemainingHours
);

// ── Session ─────────────────────────────────────────────────────────────

public record SessionInfo(string SessionId);

public record SessionCleared(string Status, string NewSessionId);

// ── Settings ────────────────────────────────────────────────────────────

public record SessionSettings(
    string Tone = "neutral",
    string CustomPrompt = "",
    string ThinkingDisplay = "hidden"
);

public record SettingsUpdateRequest(
    string? Tone = null,
    string? CustomPrompt = null,
    string? ThinkingDisplay = null
);

// ── Commands ────────────────────────────────────────────────────────────

public record CommandExecuteRequest(
    string Command,
    Dictionary<string, object>? Args = null
);

public record CommandInfo(
    string Command,
    string Title,
    string Description,
    string Method,
    string Path,
    List<string> Clients,
    string ResponseMode,
    string? Group = null
);

// ── Feedback ────────────────────────────────────────────────────────────

public record FeedbackRequest(
    string QualityLabel,
    int? QualityScore = null,
    string FeedbackText = "",
    string? InteractionId = null,
    string? Prompt = null,      // user message the rated answer replied to
    string? Response = null     // rated assistant answer (Metis dataset: instruction/output)
);

public record FeedbackResponse(bool Ok);

// ── Chat (SignalR messages) ─────────────────────────────────────────────

public record ChatHubMessage
{
    [JsonPropertyName("type")]
    public string Type { get; init; } = "";

    [JsonPropertyName("message")]
    public string? Message { get; init; }

    [JsonPropertyName("session_id")]
    public string? SessionId { get; init; }

    [JsonPropertyName("mode")]
    public string? Mode { get; init; }

    [JsonPropertyName("model")]
    public string? Model { get; init; }

    [JsonPropertyName("question_id")]
    public string? QuestionId { get; init; }

    [JsonPropertyName("answer")]
    public string? Answer { get; init; }

    /// <summary>"Crea con Hestia" drawer: page context packet (where the user is, what is selected).
    /// Appended to the client instructions of this turn only.</summary>
    [JsonPropertyName("context")]
    public string? Context { get; init; }
}

// ── Oracle NDJSON event (generic) ───────────────────────────────────────

public record OracleEvent(
    [property: JsonPropertyName("type")]
    string Type,
    [property: JsonPropertyName("content")]
    string? Content = null,
    [property: JsonPropertyName("text")]
    string? Text = null,
    [property: JsonPropertyName("action")]
    string? Action = null,
    [property: JsonPropertyName("turn")]
    int? Turn = null,
    [property: JsonPropertyName("tool")]
    string? Tool = null,
    [property: JsonPropertyName("reply")]
    string? Reply = null,
    [property: JsonPropertyName("domain")]
    string? Domain = null,
    [property: JsonPropertyName("session_id")]
    string? SessionId = null,
    [property: JsonPropertyName("event")]
    string? Event = null,
    [property: JsonPropertyName("question_id")]
    string? QuestionId = null,
    [property: JsonPropertyName("header")]
    string? Header = null,
    [property: JsonPropertyName("prompt")]
    string? Prompt = null,
    // object: Oracle options may be strings or {label, value} objects.
    [property: JsonPropertyName("options")]
    object? Options = null,
    [property: JsonPropertyName("data")]
    object? Data = null,
    [property: JsonPropertyName("metadata")]
    object? Metadata = null,
    // Question protocol: free_text | single_choice | multi_choice | confirm
    [property: JsonPropertyName("kind")]
    string? Kind = null,
    [property: JsonPropertyName("required")]
    bool? Required = null,
    [property: JsonPropertyName("timeout_sec")]
    int? TimeoutSec = null,
    // needs_input frames (non-interactive callers)
    [property: JsonPropertyName("missing_fields")]
    object? MissingFields = null,
    // notice packets (standard system messages — see Hestia-Shared/hestia-shared.md § Response packets)
    [property: JsonPropertyName("level")]
    string? Level = null,
    [property: JsonPropertyName("icon")]
    string? Icon = null,
    [property: JsonPropertyName("emoji")]
    string? Emoji = null,
    [property: JsonPropertyName("title")]
    string? Title = null,
    [property: JsonPropertyName("detail")]
    string? Detail = null
);
