namespace Hestia.WebUI.Controllers;

using System.Text.Json;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.ModelBinding;
using Hestia.WebUI.Services;

/// <summary>
/// Themis → WebUI (through Hub), same contract as <c>hestia_common.settings_client.router()</c>:
/// effective values of WebUI's own settings and live reload. Internal network only.
/// </summary>
[ApiController]
[Route("api/settings")]
[InternalNetworkGuard]
public class ThemisSettingsController : ControllerBase
{
    private readonly WebUISettings _settings;
    private readonly IServiceScopeFactory _scopes;

    public ThemisSettingsController(WebUISettings settings, IServiceScopeFactory scopes)
    {
        _settings = settings;
        _scopes = scopes;
    }

    [HttpGet("effective")]
    public IActionResult Effective() => Ok(new Dictionary<string, object?>
    {
        ["owner"] = WebUISettings.Owner, ["loaded"] = _settings.Loaded,
        ["values"] = _settings.Values(), ["pending_restart"] = Array.Empty<string>(),
    });

    [HttpPost("reload")]
    public async Task<IActionResult> Reload([FromBody(EmptyBodyBehavior = EmptyBodyBehavior.Allow)] JsonElement body)
    {
        List<string> changed;
        if (body.ValueKind == JsonValueKind.Object && body.TryGetProperty("values", out var values)
            && values.ValueKind == JsonValueKind.Object)
            changed = _settings.Apply(values);
        else
        {   // no values given: fetch them (register answers with the stored values)
            var before = _settings.LocalWithoutToken;
            using var scope = _scopes.CreateScope();
            await _settings.RegisterAsync(scope.ServiceProvider.GetRequiredService<HubClient>(), HttpContext.RequestAborted);
            changed = new List<string>();
            if (before != _settings.LocalWithoutToken) changed.Add(WebUISettings.LocalWithoutTokenKey);
        }
        return Ok(new Dictionary<string, object?>
        {
            ["owner"] = WebUISettings.Owner, ["applied"] = changed, ["pending_restart"] = Array.Empty<string>(),
        });
    }
}
