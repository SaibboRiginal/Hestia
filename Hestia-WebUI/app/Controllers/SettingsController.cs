namespace Hestia.WebUI.Controllers;

using Microsoft.AspNetCore.Mvc;
using Hestia.WebUI.Models;
using Hestia.WebUI.Services;

[ApiController]
[Route("api/webui/settings")]
public class SettingsController : ControllerBase
{
    private readonly SessionManager _sessionManager;
    private readonly ILogger<SettingsController> _logger;

    public SettingsController(SessionManager sessionManager, ILogger<SettingsController> logger)
    {
        _sessionManager = sessionManager;
        _logger = logger;
    }

    [HttpGet]
    public IActionResult Get()
    {
        var s = _sessionManager.GetSettings();
        return Ok(new
        {
            settings = new SessionSettings(
                Tone: s.GetValueOrDefault("tone", "neutral"),
                CustomPrompt: s.GetValueOrDefault("custom_prompt", ""),
                ThinkingDisplay: s.GetValueOrDefault("thinking_display", "hidden")
            )
        });
    }

    [HttpPut]
    public IActionResult Update([FromBody] SettingsUpdateRequest req)
    {
        var validTones = new HashSet<string> { "warm", "neutral", "direct", "formal" };
        var validModes = new HashSet<string> { "hidden", "compact", "detailed" };

        if (req.Tone is not null)
        {
            var tone = req.Tone.Trim().ToLowerInvariant();
            if (validTones.Contains(tone))
            {
                _sessionManager.SetSetting("tone", tone);
                _logger.LogInformation("event=webui_tone_updated tone={Tone}", tone);
            }
        }

        if (req.CustomPrompt is not null)
        {
            _sessionManager.SetSetting("custom_prompt", req.CustomPrompt.Trim());
            _logger.LogInformation("event=webui_custom_prompt_updated");
        }

        if (req.ThinkingDisplay is not null)
        {
            var mode = req.ThinkingDisplay.Trim().ToLowerInvariant();
            if (validModes.Contains(mode))
            {
                _sessionManager.SetSetting("thinking_display", mode);
                _logger.LogInformation("event=webui_thinking_display_updated mode={Mode}", mode);
            }
        }

        return Get();
    }

    [HttpPost("reset")]
    public IActionResult Reset()
    {
        _sessionManager.ResetSettings();
        _logger.LogInformation("event=webui_settings_reset");
        return Get();
    }
}
