namespace Hestia.WebUI.Services;

using System.Collections.Concurrent;
using Microsoft.Extensions.Options;
using Hestia.WebUI.Models;

/// <summary>
/// Manages session UUID and per-session settings for the single WebUI user.
/// Mirrors Telegram's session_store.py but in-memory (single-user).
/// </summary>
public class SessionManager
{
    private const string WebUIUserId = "webui_user";
    private readonly ConcurrentDictionary<string, string> _sessions = new();
    private readonly ConcurrentDictionary<string, ConcurrentDictionary<string, string>> _settings = new();
    private readonly ConcurrentDictionary<string, string> _lastMessages = new();
    private readonly ILogger<SessionManager> _logger;
    private readonly string _baseInstructions;

    public SessionManager(IOptions<WebUIOptions> options, ILogger<SessionManager> logger)
    {
        _logger = logger;
        _baseInstructions = options.Value.OracleClientInstructions;
    }

    // ── Session ID ─────────────────────────────────────────────────────

    public string GetOrCreateSession(string userId = WebUIUserId)
    {
        return _sessions.GetOrAdd(userId, _ =>
        {
            var id = Guid.NewGuid().ToString();
            _logger.LogInformation("event=webui_session_created user={User} session={Session}", userId, id);
            return id;
        });
    }

    public string GetSession(string userId = WebUIUserId) => GetOrCreateSession(userId);

    public async Task<string> ResetSessionAsync(HubClient? hub, string userId = WebUIUserId)
    {
        _sessions.TryRemove(userId, out var oldSession);
        var newSession = Guid.NewGuid().ToString();
        _sessions[userId] = newSession;

        if (oldSession is not null && hub is not null)
        {
            try
            {
                await hub.RouteDeleteAsync("oracle", $"/api/chat/{oldSession}");
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex,
                    "event=webui_session_oracle_purge_failed session={Session}", oldSession);
            }
        }

        _logger.LogInformation(
            "event=webui_session_reset user={User} old={Old} new={New}",
            userId, oldSession, newSession);
        return newSession;
    }

    // ── Settings ───────────────────────────────────────────────────────

    public Dictionary<string, string> GetSettings(string userId = WebUIUserId)
    {
        var dict = _settings.GetOrAdd(userId, _ => new ConcurrentDictionary<string, string>());
        return new Dictionary<string, string>(dict);
    }

    public string GetSetting(string key, string userId = WebUIUserId, string defaultValue = "")
    {
        var dict = _settings.GetOrAdd(userId, _ => new ConcurrentDictionary<string, string>());
        return dict.TryGetValue(key, out var value) ? value : defaultValue;
    }

    public void SetSetting(string key, string value, string userId = WebUIUserId)
    {
        var dict = _settings.GetOrAdd(userId, _ => new ConcurrentDictionary<string, string>());
        dict[key] = value;
        _logger.LogInformation("event=webui_setting_updated user={User} key={Key}", userId, key);
    }

    public void UpdateSettings(Dictionary<string, string> settings, string userId = WebUIUserId)
    {
        foreach (var (key, value) in settings)
            SetSetting(key, value, userId);
    }

    public void ResetSettings(string userId = WebUIUserId)
    {
        _settings.TryRemove(userId, out _);
        _logger.LogInformation("event=webui_settings_reset user={User}", userId);
    }

    // ── Last Message ───────────────────────────────────────────────────

    public void SetLastMessage(string message, string userId = WebUIUserId)
        => _lastMessages[userId] = message;

    public string GetLastMessage(string userId = WebUIUserId)
        => _lastMessages.TryGetValue(userId, out var msg) ? msg : "";

    // ── Client Instructions ────────────────────────────────────────────

    public string BuildClientInstructions(string userId = WebUIUserId)
    {
        // Only settings that change the answer go to Oracle (thinking_display is a
        // pure UI choice, and raw "key: value" lines were noise in the prompt).
        var parts = new List<string> { _baseInstructions };
        var settings = GetSettings(userId);
        var tone = settings.GetValueOrDefault("tone", "neutral");
        var toneLine = tone switch
        {
            "warm" => "Tono: caldo e amichevole.",
            "direct" => "Tono: diretto, essenziale, niente preamboli.",
            "formal" => "Tono: formale e professionale.",
            _ => "",
        };
        if (toneLine.Length > 0) parts.Add(toneLine);
        var custom = settings.GetValueOrDefault("custom_prompt", "");
        if (!string.IsNullOrWhiteSpace(custom)) parts.Add($"Istruzioni dell'utente: {custom.Trim()}");
        return string.Join("\n", parts.Where(p => !string.IsNullOrWhiteSpace(p)));
    }
}
