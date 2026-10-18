namespace Hestia.WebUI.Controllers;

using System.Text.Json;
using Microsoft.AspNetCore.Mvc;
using Hestia.WebUI.Services;

/// <summary>
/// Client plugins (docs/work/2026-10-17-client-plugins §4.7): catalog for the frontend, bundle files, and the
/// proxy a plugin uses to call ITS OWN module (paths under its manifest's <c>api_prefix</c>, 403 otherwise).
/// Browser → WebUI → Hub → module. Token-protected by the middleware (images accept <c>?token=</c>).
/// </summary>
[ApiController]
[Route("api/webui/plugins")]
public class PluginsController : ControllerBase
{
    private static readonly Dictionary<string, string> ContentTypes = new(StringComparer.OrdinalIgnoreCase)
    {
        [".js"] = "text/javascript", [".mjs"] = "text/javascript", [".css"] = "text/css",
        [".json"] = "application/json", [".svg"] = "image/svg+xml", [".map"] = "application/json",
    };

    private readonly HubClient _hub;
    private readonly PluginCatalog _catalog;
    private readonly ILogger<PluginsController> _logger;

    public PluginsController(HubClient hub, PluginCatalog catalog, ILogger<PluginsController> logger)
    {
        _hub = hub;
        _catalog = catalog;
        _logger = logger;
    }

    /// <summary>Hub catalog for client=webui (pages, widgets, quick actions, bundles, modules online state).</summary>
    [HttpGet("catalog")]
    public async Task<IActionResult> Catalog([FromQuery] bool fresh = false)
    {
        var cat = await _catalog.GetAsync(fresh, HttpContext.RequestAborted);
        return cat is JsonElement c ? Ok(c) : StatusCode(503, new { detail = "Hub non raggiungibile" });
    }

    /// <summary>A file of the module's WebUI bundle (fetched by the frontend, imported as a module).</summary>
    [HttpGet("{module}/bundle/{**file}")]
    public async Task<IActionResult> Bundle(string module, string file)
    {
        if (await _catalog.PrefixAsync(module, HttpContext.RequestAborted) is null) return NotFound();
        if (file.Contains("..") || !ContentTypes.TryGetValue(Path.GetExtension(file), out var ctype)) return NotFound();
        var (status, payload) = await _hub.RouteRawAsync(module, $"/ui/{PluginCatalog.Client}/{file}", HttpMethod.Get,
            timeoutSeconds: 15, ct: HttpContext.RequestAborted);
        if (status >= 400) return StatusCode(status == 404 ? 404 : 502, new { detail = $"{module} non raggiungibile" });
        // Hub wraps non-JSON answers as {"raw": text}; JSON files come back parsed.
        var text = payload.ValueKind == JsonValueKind.Object && payload.TryGetProperty("raw", out var raw)
            ? raw.GetString() ?? "" : payload.GetRawText();
        Response.Headers.CacheControl = "no-cache";
        return Content(text, ctype);
    }

    /// <summary>Plugin → its own module. Method, query and JSON body are forwarded; the module's status is kept.</summary>
    [AcceptVerbs("GET", "POST", "PUT", "PATCH", "DELETE")]
    [Route("{module}/call/{**path}")]
    public async Task<IActionResult> Call(string module, string path)
    {
        var target = "/" + path.TrimStart('/');
        var prefix = await _catalog.PrefixAsync(module, HttpContext.RequestAborted);
        if (prefix is null || !PluginCatalog.Allowed(prefix, target))
        {
            _logger.LogWarning("event=plugin_call_forbidden module={Module} path={Path}", module, target);
            return StatusCode(403, new { detail = "path not allowed for this plugin" });
        }
        object? body = null;
        if (Request.ContentLength > 0 || Request.Headers.TransferEncoding.Count > 0)
        {
            try { body = await JsonSerializer.DeserializeAsync<JsonElement>(Request.Body, cancellationToken: HttpContext.RequestAborted); }
            catch (JsonException) { return BadRequest(new { detail = "body must be JSON" }); }
        }
        var query = Request.Query.Where(kv => kv.Key != "token")
            .ToDictionary(kv => kv.Key, kv => kv.Value.ToString());
        var (status, payload) = await _hub.RouteRawAsync(module, target, new HttpMethod(Request.Method), body,
            query, timeoutSeconds: 30, ct: HttpContext.RequestAborted);
        return StatusCode(status, payload);
    }

    /// <summary>Image served by the module as {mime, data_b64} (or {data_url}) → bytes, for &lt;img src&gt;.</summary>
    [HttpGet("{module}/image")]
    public async Task<IActionResult> Image(string module, [FromQuery] string path)
    {
        var target = "/" + (path ?? "").TrimStart('/');
        var prefix = await _catalog.PrefixAsync(module, HttpContext.RequestAborted);
        if (prefix is null || !PluginCatalog.Allowed(prefix, target)) return StatusCode(403);
        var (status, payload) = await _hub.RouteRawAsync(module, target, HttpMethod.Get, timeoutSeconds: 20,
            ct: HttpContext.RequestAborted);
        if (status >= 400 || payload.ValueKind != JsonValueKind.Object) return StatusCode(status >= 400 ? status : 502);
        var mime = payload.TryGetProperty("mime", out var m) ? m.GetString() ?? "image/jpeg" : "image/jpeg";
        if (!mime.StartsWith("image/")) return StatusCode(415);
        var b64 = payload.TryGetProperty("data_b64", out var d) ? d.GetString() ?? "" : "";
        try
        {
            Response.Headers.CacheControl = "private, max-age=86400";
            return File(Convert.FromBase64String(b64), mime);
        }
        catch (FormatException) { return StatusCode(502); }
    }
}
