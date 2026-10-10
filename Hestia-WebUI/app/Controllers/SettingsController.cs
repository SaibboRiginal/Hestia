namespace Hestia.WebUI.Controllers;

using System.Text.Json;
using Microsoft.AspNetCore.Mvc;
using Hestia.WebUI.Models;
using Hestia.WebUI.Services;

/// <summary>
/// Impostazioni → Personali. Tone and personal instructions are central settings shared by every
/// client (Themis <c>oracle.chat.*</c>, scope profile = your defaults; Oracle applies them itself).
/// The reasoning display is a WebUI presentation choice and stays here.
/// </summary>
[ApiController]
[Route("api/webui/settings")]
public class SettingsController : ControllerBase
{
    private const string Tone = "oracle.chat.tone";
    private const string Instructions = "oracle.chat.instructions";
    private static readonly HashSet<string> ValidTones = new() { "warm", "neutral", "direct", "formal" };
    private static readonly HashSet<string> ValidModes = new() { "hidden", "compact", "detailed" };

    private readonly SessionManager _sessionManager;
    private readonly HubClient _hub;
    private readonly ILogger<SettingsController> _logger;

    public SettingsController(SessionManager sessionManager, HubClient hub, ILogger<SettingsController> logger)
    {
        _sessionManager = sessionManager;
        _hub = hub;
        _logger = logger;
    }

    [HttpGet]
    public async Task<IActionResult> Get()
    {
        var s = _sessionManager.GetSettings();
        return Ok(new
        {
            settings = new SessionSettings(
                Tone: await ProfileValue(Tone, "warm"),
                CustomPrompt: await ProfileValue(Instructions, ""),
                ThinkingDisplay: s.GetValueOrDefault("thinking_display", "hidden")
            )
        });
    }

    [HttpPut]
    public async Task<IActionResult> Update([FromBody] SettingsUpdateRequest req)
    {
        if (req.Tone is not null)
        {
            var tone = req.Tone.Trim().ToLowerInvariant();
            if (ValidTones.Contains(tone))
                await SetProfile(Tone, tone);
        }

        if (req.CustomPrompt is not null)
        {
            var text = req.CustomPrompt.Trim();
            if (text.Length == 0) await ResetProfile(Instructions);
            else await SetProfile(Instructions, text);
        }

        if (req.ThinkingDisplay is not null)
        {
            var mode = req.ThinkingDisplay.Trim().ToLowerInvariant();
            if (ValidModes.Contains(mode))
            {
                _sessionManager.SetSetting("thinking_display", mode);
                _logger.LogInformation("event=webui_thinking_display_updated mode={Mode}", mode);
            }
        }

        return await Get();
    }

    [HttpPost("reset")]
    public async Task<IActionResult> Reset()
    {
        _sessionManager.ResetSettings();
        await ResetProfile(Tone);
        await ResetProfile(Instructions);
        _logger.LogInformation("event=webui_settings_reset");
        return await Get();
    }

    // ── Themis (via Hub) ───────────────────────────────────────────────

    private static string KeyPath(string key) => $"/api/settings/key/{Uri.EscapeDataString(key)}";

    /// <summary>Profile value (no client/session layer) or the declared default; Themis down → fallback.</summary>
    private async Task<string> ProfileValue(string key, string fallback)
    {
        try
        {
            var item = await _hub.RouteGetAsync("themis", KeyPath(key), null, 5);
            if (item.TryGetProperty("value", out var v) && v.ValueKind == JsonValueKind.String)
                return v.GetString() ?? fallback;
        }
        catch (Exception ex)
        {
            _logger.LogWarning("[🔄] event=webui_personal_setting_read_failed key={Key} error={Error} fallback=default",
                key, ex.Message);
        }
        return fallback;
    }

    private async Task SetProfile(string key, string value)
    {
        await _hub.RoutePutAsync("themis", KeyPath(key), new Dictionary<string, object?>
        {
            ["value"] = value, ["scope"] = "profile", ["actor"] = "webui",
        });
        _logger.LogInformation("event=webui_personal_setting_updated key={Key}", key);
    }

    private async Task ResetProfile(string key)
    {
        try
        {
            await _hub.RouteAsyncPublic("themis", KeyPath(key), HttpMethod.Delete,
                query: new Dictionary<string, string> { ["scope"] = "profile", ["actor"] = "webui" });
        }
        catch (Exception ex)
        {
            _logger.LogWarning("event=webui_personal_setting_reset_failed key={Key} error={Error}", key, ex.Message);
        }
    }
}
