namespace Hestia.WebUI.Controllers;

using System.Text.Json;
using Microsoft.AspNetCore.Mvc;
using Hestia.WebUI.Services;

/// <summary>
/// Page «Download» (SPEC docs/work/2026-10-30-setup-un-click §4.3): every module downloads its own things
/// (hestia_common.downloads, capability <c>downloads</c>); this controller lists them all and forwards the buttons
/// (pausa, riprendi, riprova, annulla, elimina) to the owner. Browser → WebUI → Hub → module.
/// </summary>
[ApiController]
[Route("api/webui/downloads")]
public class DownloadsController : ControllerBase
{
    private static readonly HashSet<string> Ops = new() { "pause", "resume", "retry", "cancel", "remove" };
    private readonly HubClient _hub;
    private readonly ILogger<DownloadsController> _logger;

    public DownloadsController(HubClient hub, ILogger<DownloadsController> logger)
    {
        _hub = hub;
        _logger = logger;
    }

    private async Task<List<string>> ModulesAsync(CancellationToken ct)
    {
        var res = await _hub.GetServicesAsync(ct);
        var names = new List<string>();
        if (res.TryGetProperty("services", out var services) && services.ValueKind == JsonValueKind.Array)
            foreach (var svc in services.EnumerateArray())
                if (svc.TryGetProperty("name", out var n) && svc.TryGetProperty("capabilities", out var caps)
                    && caps.ValueKind == JsonValueKind.Object && caps.TryGetProperty("downloads", out _))
                    names.Add(n.GetString() ?? "");
        return names.Where(n => n.Length > 0).OrderBy(n => n).ToList();
    }

    /// <summary><c>{downloads: [{module, id, what, source, size, done, speed, eta_s, state, error}], offline: [module]}</c></summary>
    [HttpGet]
    public async Task<IActionResult> List()
    {
        List<string> modules;
        try { modules = await ModulesAsync(HttpContext.RequestAborted); }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or JsonException)
        {
            _logger.LogWarning("[🔄] event=webui_downloads_modules_failed error={Error}", ex.Message);
            return StatusCode(503, new { detail = "Hub non raggiungibile" });
        }
        var calls = modules.Select(async m => (m, await _hub.RouteRawAsync(m, "/api/downloads", HttpMethod.Get,
            timeoutSeconds: 8, ct: HttpContext.RequestAborted)));
        var items = new List<JsonElement>();
        var offline = new List<string>();
        foreach (var (module, (status, payload)) in await Task.WhenAll(calls))
        {
            if (status >= 400 || !payload.TryGetProperty("downloads", out var list) || list.ValueKind != JsonValueKind.Array)
            {
                offline.Add(module);
                continue;
            }
            items.AddRange(list.EnumerateArray().Select(j => j.Clone()));
        }
        return Ok(new { downloads = items, offline });
    }

    /// <summary>Body <c>{id}</c> (ids carry «:», so not in the path).</summary>
    [HttpPost("{module}/{op}")]
    public async Task<IActionResult> Op(string module, string op, [FromBody] JsonElement body)
    {
        if (!Ops.Contains(op)) return NotFound();
        var id = body.TryGetProperty("id", out var i) ? i.GetString() ?? "" : "";
        if (id.Length == 0 || id.Length > 200) return BadRequest(new { detail = "id mancante" });
        try
        {
            if (!(await ModulesAsync(HttpContext.RequestAborted)).Contains(module))
                return NotFound(new { detail = "modulo senza download" });
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or JsonException)
        {
            return StatusCode(503, new { detail = "Hub non raggiungibile" });
        }
        var (status, payload) = await _hub.RouteRawAsync(module, $"/api/downloads/{id}/{op}", HttpMethod.Post,
            timeoutSeconds: 30, ct: HttpContext.RequestAborted);
        return new ContentResult
        {
            StatusCode = status,
            ContentType = "application/json",
            Content = payload.ValueKind == JsonValueKind.Undefined ? "{}" : payload.GetRawText(),
        };
    }
}
