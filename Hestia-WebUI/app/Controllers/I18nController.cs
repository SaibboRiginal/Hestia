namespace Hestia.WebUI.Controllers;

using System.Text.Json;
using Microsoft.AspNetCore.Mvc;
using Hestia.WebUI.Services;

/// <summary>
/// Fixed texts of the shell and the plugins in the owner's language (dossier docs/work/2026-11-14-backend-inglese):
/// browser → WebUI → Hub → Themis /api/settings/i18n → {language, messages (Italian source → translation)}.
/// Public like /auth/access: the login page needs it too and it carries no personal data.
/// </summary>
[ApiController]
[Route("api/webui/i18n")]
public class I18nController : ControllerBase
{
    private readonly HubClient _hub;
    private readonly ILogger<I18nController> _logger;

    public I18nController(HubClient hub, ILogger<I18nController> logger)
    {
        _hub = hub;
        _logger = logger;
    }

    [HttpGet]
    public async Task<IActionResult> Get() => Ok(await Catalog());

    /// <summary>The same catalog as a script for index.html: it runs before the app bundle, so every text of the
    /// shell and the plugins (module-level constants too) is already in the owner's language.</summary>
    [HttpGet("~/api/webui/i18n.js")]
    public async Task<IActionResult> Script()
    {
        var json = JsonSerializer.Serialize(await Catalog());
        Response.Headers.CacheControl = "no-store";
        return Content($"globalThis.__hestiaI18n = {json};\n", "text/javascript; charset=utf-8");
    }

    private async Task<object> Catalog()
    {
        // Short timeout: the page waits for this script before drawing anything.
        var (status, payload) = await _hub.RouteRawAsync("themis", "/api/settings/i18n", HttpMethod.Get, timeoutSeconds: 3);
        if (status < 400 && payload.ValueKind == JsonValueKind.Object && payload.TryGetProperty("messages", out _))
            return payload;
        // Unreachable settings: Italian source texts (empty map), never an error page.
        _logger.LogWarning("[🔄] event=webui_i18n_unavailable status={Status}", status);
        return new { language = "it", messages = new Dictionary<string, string>() };
    }
}
