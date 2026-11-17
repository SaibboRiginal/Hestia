namespace Hestia.WebUI.Controllers;

using System.Text.Json;
using Microsoft.AspNetCore.Mvc;
using Hestia.WebUI.Services;

/// <summary>
/// Fixed texts of the shell and the plugins in the owner's language (dossier docs/work/2026-11-14-backend-inglese):
/// browser → WebUI → Hub → Themis /api/settings/i18n → {language, messages (English source → translation)}.
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
        // The tab is called with the assistant's name from the first paint (docs/work/2026-11-17-nome-dei-client).
        return Content($"globalThis.__hestiaI18n = {json};\nif (globalThis.__hestiaI18n.assistant) document.title = globalThis.__hestiaI18n.assistant;\n",
            "text/javascript; charset=utf-8");
    }

    /// <summary>The installed app (PWA) is called with the name the owner gave the assistant
    /// (docs/work/2026-11-17-nome-dei-client): the manifest is written from the catalog, Hestia when unknown.</summary>
    [HttpGet("~/api/webui/manifest.webmanifest")]
    public async Task<IActionResult> Manifest()
    {
        var json = JsonSerializer.SerializeToElement(await Catalog());
        var name = json.TryGetProperty("assistant", out var a) && a.ValueKind == JsonValueKind.String
            && a.GetString() is { Length: > 0 } n ? n : "Hestia";
        var lang = json.TryGetProperty("language", out var l) && l.ValueKind == JsonValueKind.String ? l.GetString() ?? "en" : "en";
        var description = "Personal assistant";
        if (json.TryGetProperty("messages", out var m) && m.ValueKind == JsonValueKind.Object
            && m.TryGetProperty(description, out var t) && t.ValueKind == JsonValueKind.String && t.GetString() is { Length: > 0 } d)
            description = d;
        var manifest = new Dictionary<string, object>
        {
            ["name"] = name, ["short_name"] = name, ["description"] = $"{name}, {description.ToLowerInvariant()}",
            ["lang"] = lang, ["start_url"] = "/home", ["scope"] = "/", ["display"] = "standalone",
            ["background_color"] = "#121212", ["theme_color"] = "#121212",
            ["icons"] = new[] { new Dictionary<string, string> { ["src"] = "/icon.svg", ["sizes"] = "any", ["type"] = "image/svg+xml", ["purpose"] = "any maskable" } },
        };
        Response.Headers.CacheControl = "no-store";
        return Content(JsonSerializer.Serialize(manifest), "application/manifest+json; charset=utf-8");
    }

    private async Task<object> Catalog()
    {
        // Short timeout: the page waits for this script before drawing anything.
        var (status, payload) = await _hub.RouteRawAsync("themis", "/api/settings/i18n", HttpMethod.Get, timeoutSeconds: 3);
        if (status < 400 && payload.ValueKind == JsonValueKind.Object && payload.TryGetProperty("messages", out _))
            return payload;
        // Unreachable settings: the English source texts (empty map), never an error page.
        _logger.LogWarning("[🔄] event=webui_i18n_unavailable status={Status}", status);
        return new { language = "en", messages = new Dictionary<string, string>() };
    }
}
