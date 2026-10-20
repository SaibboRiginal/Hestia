namespace Hestia.WebUI.Controllers;

using System.IO.Compression;
using System.Text;
using System.Text.Json;
using Microsoft.AspNetCore.Mvc;
using Hestia.WebUI.Services;

/// <summary>
/// Esporta e importa (docs/work/2026-10-20-import-export): the page in Impostazioni builds and reads the
/// <c>.hestia</c> file; every module exports/imports only its own data through <c>/api/transfer/*</c>
/// (hestia_common.transfer) and Themis does the settings. This controller forwards to modules that advertise the
/// <c>transfer</c> capability (nothing else) and keeps the restore points: before an import the page saves the
/// target's current copy of the same sections as an Archive blob (owner <c>webui</c>, gzip JSON), the newest
/// <c>webui.transfer.restore_points</c> are kept. Browser → WebUI → Hub → module.
/// </summary>
[ApiController]
[Route("api/webui/transfer")]
public class TransferController : ControllerBase
{
    private const string RestoreKind = "transfer-restore";
    private static readonly HashSet<string> Actions = new() { "items", "export", "import", "files" };

    private readonly HubClient _hub;
    private readonly WebUISettings _settings;
    private readonly IHttpClientFactory _http;
    private readonly IConfiguration _config;
    private readonly ILogger<TransferController> _logger;

    public TransferController(HubClient hub, WebUISettings settings, IHttpClientFactory http, IConfiguration config,
        ILogger<TransferController> logger)
    {
        _hub = hub;
        _settings = settings;
        _http = http;
        _config = config;
        _logger = logger;
    }

    /// <summary>Registered services with the transfer capability (Hub registry, no health probe).</summary>
    private async Task<Dictionary<string, JsonElement>> TransferModulesAsync(CancellationToken ct)
    {
        var hubUrl = (Environment.GetEnvironmentVariable("HUB_API_URL") ?? _config["Hestia:HubApiUrl"]
                      ?? "http://hestia_hub:19001/api").TrimEnd('/');
        var res = await _http.CreateClient().GetFromJsonAsync<JsonElement>($"{hubUrl}/registry/services", ct);
        var outMap = new Dictionary<string, JsonElement>();
        if (res.TryGetProperty("services", out var services) && services.ValueKind == JsonValueKind.Array)
            foreach (var svc in services.EnumerateArray())
                if (svc.TryGetProperty("name", out var n) && svc.TryGetProperty("capabilities", out var caps)
                    && caps.ValueKind == JsonValueKind.Object && caps.TryGetProperty("transfer", out var t)
                    && t.ValueKind == JsonValueKind.Object)
                    outMap[n.GetString() ?? ""] = t;
        return outMap;
    }

    /// <summary>Modules that take part: <c>[{module, settings, sections}]</c> (titles come from the plugin catalog).</summary>
    [HttpGet("modules")]
    public async Task<IActionResult> Modules()
    {
        try
        {
            var mods = await TransferModulesAsync(HttpContext.RequestAborted);
            return Ok(new
            {
                modules = mods.OrderBy(kv => kv.Key).Select(kv => new
                {
                    module = kv.Key,
                    settings = kv.Value.TryGetProperty("settings", out var s) && s.ValueKind == JsonValueKind.True,
                }),
            });
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or JsonException)
        {
            _logger.LogWarning("[🔄] event=webui_transfer_modules_failed error={Error}", ex.Message);
            return StatusCode(503, new { detail = "Hub non raggiungibile" });
        }
    }

    private async Task<bool> AllowedAsync(string module)
    {
        try { return (await TransferModulesAsync(HttpContext.RequestAborted)).ContainsKey(module); }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or JsonException) { return false; }
    }

    [HttpGet("{module}/describe")]
    public async Task<IActionResult> Describe(string module)
    {
        if (!await AllowedAsync(module)) return NotFound(new { detail = "modulo senza esporta/importa" });
        var (status, payload) = await _hub.RouteRawAsync(module, "/api/transfer/describe", HttpMethod.Get,
            timeoutSeconds: 30, ct: HttpContext.RequestAborted);
        return StatusCode(status, payload);
    }

    [HttpGet("{module}/files/{id}")]
    public async Task<IActionResult> File(string module, string id)
    {
        if (!await AllowedAsync(module)) return NotFound(new { detail = "modulo senza esporta/importa" });
        var (status, payload) = await _hub.RouteRawAsync(module, $"/api/transfer/files/{Uri.EscapeDataString(id)}",
            HttpMethod.Get, timeoutSeconds: 60, ct: HttpContext.RequestAborted);
        return StatusCode(status, payload);
    }

    /// <summary>items · export · import · files (upload): JSON body forwarded, the module's status kept.</summary>
    [HttpPost("{module}/{action}")]
    public async Task<IActionResult> Forward(string module, string action, [FromBody] JsonElement body)
    {
        if (!Actions.Contains(action)) return NotFound();
        if (!await AllowedAsync(module)) return NotFound(new { detail = "modulo senza esporta/importa" });
        var (status, payload) = await _hub.RouteRawAsync(module, $"/api/transfer/{action}", HttpMethod.Post, body,
            timeoutSeconds: action == "items" ? 30 : 120, ct: HttpContext.RequestAborted);
        return StatusCode(status, payload);
    }

    // ── restore points (Archive blobs of the WebUI) ──────────────────────────

    [HttpGet("restore-points")]
    public async Task<IActionResult> RestorePoints()
    {
        var (status, payload) = await _hub.RouteRawAsync("archive", "/api/blobs", HttpMethod.Get,
            query: new() { ["owner_module"] = WebUISettings.Owner, ["limit"] = "200" }, timeoutSeconds: 15,
            ct: HttpContext.RequestAborted);
        if (status >= 400) return StatusCode(status, payload);
        return Ok(new { items = Restore(payload).Select(View), keep = _settings.TransferRestorePoints });
    }

    private static IEnumerable<JsonElement> Restore(JsonElement list) =>
        list.TryGetProperty("items", out var items) && items.ValueKind == JsonValueKind.Array
            ? items.EnumerateArray().Where(b => b.TryGetProperty("meta", out var m) && m.ValueKind == JsonValueKind.Object
                && m.TryGetProperty("kind", out var k) && k.GetString() == RestoreKind)
            : Enumerable.Empty<JsonElement>();

    private static object View(JsonElement b)
    {
        var meta = b.GetProperty("meta");
        return new
        {
            id = b.GetProperty("blob_id").GetString(),
            created_at = b.TryGetProperty("created_at", out var c) ? c.GetString() : null,
            size = b.TryGetProperty("size", out var s) && s.ValueKind == JsonValueKind.Number ? s.GetInt64() : 0,
            label = meta.TryGetProperty("label", out var l) ? l.GetString() : null,
            modules = meta.TryGetProperty("modules", out var m) ? m : default,
        };
    }

    /// <summary>Save a restore point: body = <c>{label, modules, file}</c> (file = the .hestia JSON object).</summary>
    [HttpPost("restore-points")]
    public async Task<IActionResult> SaveRestorePoint([FromBody] JsonElement body)
    {
        if (body.ValueKind != JsonValueKind.Object || !body.TryGetProperty("file", out var file))
            return BadRequest(new { detail = "file obbligatorio" });
        byte[] gz;
        using (var ms = new MemoryStream())
        {
            using (var zip = new GZipStream(ms, CompressionLevel.Optimal, leaveOpen: true))
                zip.Write(Encoding.UTF8.GetBytes(file.GetRawText()));
            gz = ms.ToArray();
        }
        var meta = new Dictionary<string, object?>
        {
            ["kind"] = RestoreKind,
            ["label"] = body.TryGetProperty("label", out var l) ? l.GetString() : "Prima dell'importazione",
            ["modules"] = body.TryGetProperty("modules", out var m) ? m : null,
            ["at"] = DateTimeOffset.UtcNow.ToString("o"),
        };
        var (status, payload) = await _hub.RouteRawAsync("archive", "/api/blobs", HttpMethod.Post, new Dictionary<string, object?>
        {
            ["owner_module"] = WebUISettings.Owner, ["content_type"] = "application/gzip",
            ["data_base64"] = Convert.ToBase64String(gz), ["meta"] = meta,
        }, timeoutSeconds: 60, ct: HttpContext.RequestAborted);
        if (status >= 400) return StatusCode(status, payload);
        await PruneAsync();
        _logger.LogInformation("event=webui_transfer_restore_point_saved bytes={Bytes}", gz.Length);
        return Ok(new { id = payload.TryGetProperty("blob_id", out var id) ? id.GetString() : null });
    }

    /// <summary>Keep the newest N restore points (Themis <c>webui.transfer.restore_points</c>).</summary>
    private async Task PruneAsync()
    {
        var (status, payload) = await _hub.RouteRawAsync("archive", "/api/blobs", HttpMethod.Get,
            query: new() { ["owner_module"] = WebUISettings.Owner, ["limit"] = "200" }, timeoutSeconds: 15);
        if (status >= 400) return;
        foreach (var old in Restore(payload).Skip(_settings.TransferRestorePoints))
            await _hub.RouteRawAsync("archive", $"/api/blobs/{old.GetProperty("blob_id").GetString()}",
                HttpMethod.Delete, timeoutSeconds: 15);
    }

    /// <summary>The restore point as the .hestia JSON object (the page imports it with «Sostituisci»).</summary>
    [HttpGet("restore-points/{id}")]
    public async Task<IActionResult> RestorePoint(string id)
    {
        var (status, payload) = await _hub.RouteRawAsync("archive", $"/api/blobs/{Uri.EscapeDataString(id)}/meta",
            HttpMethod.Get, timeoutSeconds: 15, ct: HttpContext.RequestAborted);
        if (status >= 400 || !Restore(JsonSerializer.SerializeToElement(new { items = new[] { payload } })).Any()
            || payload.GetProperty("owner_module").GetString() != WebUISettings.Owner)
            return NotFound();
        (status, payload) = await _hub.RouteRawAsync("archive", $"/api/blobs/{Uri.EscapeDataString(id)}/base64",
            HttpMethod.Get, timeoutSeconds: 60, ct: HttpContext.RequestAborted);
        if (status >= 400) return StatusCode(status, payload);
        var raw = Convert.FromBase64String(payload.GetProperty("data_b64").GetString() ?? "");
        using var zip = new GZipStream(new MemoryStream(raw), CompressionMode.Decompress);
        using var reader = new StreamReader(zip, Encoding.UTF8);
        return Content(await reader.ReadToEndAsync(), "application/json");
    }

    [HttpDelete("restore-points/{id}")]
    public async Task<IActionResult> DeleteRestorePoint(string id)
    {
        var (status, payload) = await _hub.RouteRawAsync("archive", $"/api/blobs/{Uri.EscapeDataString(id)}/meta",
            HttpMethod.Get, timeoutSeconds: 15, ct: HttpContext.RequestAborted);
        if (status >= 400 || payload.GetProperty("owner_module").GetString() != WebUISettings.Owner) return NotFound();
        (status, payload) = await _hub.RouteRawAsync("archive", $"/api/blobs/{Uri.EscapeDataString(id)}",
            HttpMethod.Delete, timeoutSeconds: 15, ct: HttpContext.RequestAborted);
        return StatusCode(status, payload);
    }
}
