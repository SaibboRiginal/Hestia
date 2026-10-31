namespace Hestia.WebUI.Controllers;

using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.AspNetCore.Mvc;
using Hestia.WebUI.Services;

/// <summary>
/// Voice in the WebUI (dossier docs/work/2026-10-20-modulo-voce §7): token-protected proxy to the voice
/// module through the Hub. The browser records and plays; listening and speaking happen in the voice module.
/// <list type="bullet">
/// <item><c>POST /api/webui/voice/transcribe</c> — a voice message of the chat (kept with its message).</item>
/// <item><c>POST /api/webui/voice/speak</c> — «Ascolta» under a reply (the audio is kept with the reply).</item>
/// <item><c>POST /api/webui/voice/listen[/{sid}/chunk|end]</c>, <c>say[/{sid}/text|end]</c> — live mode «Parla»:
/// the microphone in chunks, the answer spoken sentence by sentence while it is written.</item>
/// <item><c>GET /api/webui/voice/live</c> — live settings (the pause that closes a turn).</item>
/// <item><c>GET /api/webui/voice/audio-for?ref_id=</c>, <c>/audio/{id}</c> — play a kept audio again.</item>
/// </list>
/// The WebUI only picks its own uses (<see cref="UseCases"/>) and adds its session to what is kept.
/// </summary>
[ApiController]
[Route("api/webui/voice")]
public class VoiceController : ControllerBase
{
    public const string UseMessage = "webui.vocale";
    public const string UseListen = "webui.ascolta";
    public const string UseLiveIn = "webui.live.ascolto";
    public const string UseLiveOut = "webui.live.voce";
    public const string UseDictation = "webui.dettatura";

    /// <summary>Declared on the Hub (capabilities.voice_usecases).</summary>
    public static readonly object[] UseCases =
    {
        new { id = UseMessage, label = "Sito · vocali in chat", direction = "ascolto", chain = "ascolto", mode = "segui",
              help = "I vocali che registri nella chat del sito." },
        new { id = UseListen, label = "Sito · «Ascolta»", direction = "voce", chain = "voce", mode = "segui",
              help = "Il tasto «Ascolta» sotto le risposte." },
        new { id = UseLiveIn, label = "Sito · Parla (ascolto)", direction = "ascolto", chain = "ascolto", mode = "segui",
              help = "Modalità Parla: quello che dici." },
        new { id = UseLiveOut, label = "Sito · Parla (voce)", direction = "voce", chain = "voce", mode = "segui",
              help = "Modalità Parla: le risposte lette mentre si scrivono." },
        new { id = UseDictation, label = "Sito · dettatura", direction = "ascolto", chain = "ascolto", mode = "segui",
              help = "Il tasto «Detta» della chat: quello che dici diventa testo da rileggere, senza inviarlo." },
    };

    private static readonly HashSet<string> Uses = new() { UseMessage, UseListen, UseLiveIn, UseLiveOut, UseDictation };
    private static readonly Regex StreamStep = new("^(listen|say)/[A-Za-z0-9]{6,40}/(chunk|text|end)$", RegexOptions.Compiled);

    private readonly HubClient _hub;
    private readonly SessionManager _sessions;
    private readonly ILogger<VoiceController> _logger;

    public VoiceController(HubClient hub, SessionManager sessions, ILogger<VoiceController> logger)
    {
        _hub = hub;
        _sessions = sessions;
        _logger = logger;
    }

    [HttpPost("transcribe")]
    [RequestSizeLimit(41_943_040)] // 40 MB of base64
    public Task<IActionResult> Transcribe([FromBody] JsonElement body) => Forward("transcribe", body, UseMessage, 180);

    [HttpPost("speak")]
    public Task<IActionResult> Speak([FromBody] JsonElement body) => Forward("speak", body, UseListen, 120);

    [HttpPost("listen")]
    public Task<IActionResult> ListenOpen([FromBody] JsonElement body) => Forward("listen", body, UseLiveIn, 15);

    [HttpPost("say")]
    public Task<IActionResult> SayOpen([FromBody] JsonElement body) => Forward("say", body, UseLiveOut, 15);

    /// <summary>A step of an open stream: <c>listen/{sid}/chunk|end</c>, <c>say/{sid}/text|end</c>.</summary>
    [HttpPost("{kind}/{sid}/{step}")]
    [RequestSizeLimit(10_485_760)]
    public Task<IActionResult> StreamStepCall(string kind, string sid, string step, [FromBody] JsonElement body)
    {
        var path = $"{kind}/{sid}/{step}";
        if (!StreamStep.IsMatch(path))
            return Task.FromResult<IActionResult>(NotFound(new { detail = "unknown voice stream step" }));
        return Forward(path, body, null, step == "end" ? 120 : 60);
    }

    /// <summary>Queue the local voice models (guided setup «Voce», Download page): Echo picks them from its chains.</summary>
    [HttpPost("models/prefetch")]
    public Task<IActionResult> Prefetch() => Raw(HttpMethod.Post, "models/prefetch", new { }, null, 30);

    [HttpGet("live")]
    public Task<IActionResult> Live() => Raw(HttpMethod.Get, "live", null, null, 10);

    [HttpGet("audio-for")]
    public Task<IActionResult> AudioFor([FromQuery(Name = "ref_id")] string refId, [FromQuery] string format = "")
        => Raw(HttpMethod.Get, "audio-for", null, new() { ["ref_id"] = refId, ["format"] = format });

    [HttpGet("audio/{id}")]
    public Task<IActionResult> Audio(string id, [FromQuery] string format = "")
        => Raw(HttpMethod.Get, $"audio/{Uri.EscapeDataString(id)}", null, new() { ["format"] = format });

    /// <summary>Ref of a chat message in the kept-audio index (same shape as Telegram's <c>tg:chat:msg</c>).</summary>
    public static string MessageRef(string sessionId, string messageId) => $"web:{sessionId}:{messageId}";

    private Task<IActionResult> Forward(string path, JsonElement body, string? defaultUse, double timeout)
    {
        var map = body.ValueKind == JsonValueKind.Object
            ? JsonSerializer.Deserialize<Dictionary<string, object?>>(body.GetRawText()) ?? new()
            : new Dictionary<string, object?>();
        if (defaultUse is not null)
        {
            var use = map.TryGetValue("use_case", out var u) ? u?.ToString() : null;
            map["use_case"] = use is not null && Uses.Contains(use) ? use : defaultUse;
        }
        if (map.TryGetValue("keep", out var keepRaw) && keepRaw is JsonElement keepEl && keepEl.ValueKind == JsonValueKind.Object)
        {
            var sid = _sessions.GetSession();
            var keep = JsonSerializer.Deserialize<Dictionary<string, object?>>(keepEl.GetRawText()) ?? new();
            keep["client"] = "webui";
            keep["session_id"] = sid;
            if (keep.TryGetValue("message_id", out var mid) && mid?.ToString() is { Length: > 0 } m && !m.StartsWith("web:"))
                keep["message_id"] = MessageRef(sid, m);
            map["keep"] = keep;
        }
        _logger.LogInformation("event=webui_voice_call path={Path} use_case={Use}", path,
            map.TryGetValue("use_case", out var uc) ? uc : "-");
        return Raw(HttpMethod.Post, path, map, null, timeout);
    }

    private async Task<IActionResult> Raw(HttpMethod method, string path, object? body,
        Dictionary<string, string>? query, double timeout = 30)
    {
        query = query?.Where(kv => !string.IsNullOrEmpty(kv.Value)).ToDictionary(kv => kv.Key, kv => kv.Value);
        var (status, payload) = await _hub.RouteRawAsync("echo", $"/api/voice/{path}", method, body, query, timeout);
        return new ContentResult
        {
            StatusCode = status,
            ContentType = "application/json",
            Content = payload.ValueKind == JsonValueKind.Undefined ? "{}" : payload.GetRawText(),
        };
    }
}
