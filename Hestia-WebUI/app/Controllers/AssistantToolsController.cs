namespace Hestia.WebUI.Controllers;

using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Mvc;
using Hestia.WebUI.Services;

/// <summary>
/// The WebUI's own tools for the assistant (client plugins SPEC §4.6): which widgets exist and which dashboards
/// the user has. Served as REST (Hub commands: Oracle calls them by path) and as MCP JSON-RPC at <c>/api/ai/mcp</c>
/// (advertised as <c>capabilities.mcp_endpoint</c>). Read-only: a dashboard is created or changed only through
/// Themis <c>settings_propose</c> on <c>webui.dashboards</c>, confirmed by the user in the chat.
/// Outside <c>/api/webui/</c> like <c>/api/settings</c>: internal callers (Hub), no browser token.
/// </summary>
[ApiController]
public class AssistantToolsController : ControllerBase
{
    private const string DashboardsKey = "webui.dashboards";
    private readonly HubClient _hub;
    private readonly PluginCatalog _catalog;
    private readonly ILogger<AssistantToolsController> _logger;

    public AssistantToolsController(HubClient hub, PluginCatalog catalog, ILogger<AssistantToolsController> logger)
    {
        _hub = hub;
        _catalog = catalog;
        _logger = logger;
    }

    private static readonly object[] Tools =
    [
        new
        {
            name = "webui_widgets",
            title = "🧩 Widget disponibili",
            description = "Widget dei moduli per le dashboard della WebUI: id, nome, modulo, misure (s m l xl), " +
                          "parametri. Usa prima di proporre una dashboard.",
            inputSchema = new { type = "object", properties = new { q = new { type = "string", description = "filtro (nome, modulo)" } } },
            path = "/api/ai/widgets",
            clients = new[] { "ui" },
            telegram_visible = false,
            telegram_group = "impostazioni",
        },
        new
        {
            name = "webui_dashboards",
            title = "🧩 Dashboard della WebUI",
            description = "Dashboard attuali (Home + altre) con i loro widget. Per creare/cambiare: settings_propose " +
                          "key=webui.dashboards, value = TUTTO l'oggetto {dashboards:[{id,title,icon,created_by:'oracle'," +
                          "items:[{widget:'<modulo>.<id>',size,params,title}]}]} (tieni le esistenti). L'utente conferma in chat.",
            inputSchema = new { type = "object", properties = new { } },
            path = "/api/ai/dashboards",
            clients = new[] { "ui" },
            telegram_visible = false,
            telegram_group = "impostazioni",
        },
    ];

    /// <summary>Compact widget catalog (visible or not: the user decides on the card).</summary>
    [HttpGet("api/ai/widgets")]
    public async Task<IActionResult> Widgets([FromQuery] string? q = null) => Ok(await WidgetsAsync(q));

    /// <summary>Current dashboards (Themis value of webui.dashboards on the webui layer).</summary>
    [HttpGet("api/ai/dashboards")]
    public async Task<IActionResult> Dashboards() => Ok(await DashboardsAsync());

    // Module MCP of the WebUI (read by Hub/Hestia-MCP). Not /mcp: that is the public door for external AIs
    // (McpDoorController).
    [HttpPost("api/ai/mcp")]
    public async Task<IActionResult> Mcp([FromBody] JsonElement body)
    {
        var id = body.TryGetProperty("id", out var idEl) ? (object?)idEl : null;
        var method = body.TryGetProperty("method", out var m) ? m.GetString() ?? "" : "";
        if (method == "tools/list")
            return Ok(new { jsonrpc = "2.0", id, result = new { tools = Tools } });
        if (method != "tools/call")
            return Ok(new { jsonrpc = "2.0", id, error = new { code = -32601, message = $"Unknown method: {method}" } });

        var p = body.TryGetProperty("params", out var pe) ? pe : default;
        var name = p.ValueKind == JsonValueKind.Object && p.TryGetProperty("name", out var n) ? n.GetString() ?? "" : "";
        var args = p.ValueKind == JsonValueKind.Object && p.TryGetProperty("arguments", out var a) ? a : default;
        object? result = name switch
        {
            "webui_widgets" => await WidgetsAsync(args.ValueKind == JsonValueKind.Object && args.TryGetProperty("q", out var qq) ? qq.GetString() : null),
            "webui_dashboards" => await DashboardsAsync(),
            _ => null,
        };
        if (result is null)
            return Ok(new { jsonrpc = "2.0", id, error = new { code = -32601, message = $"Tool not found: {name}" } });
        _logger.LogInformation("event=mcp_tool_called service=webui tool={Tool}", name);
        return Ok(new
        {
            jsonrpc = "2.0", id,
            result = new { content = new[] { new { type = "text", text = JsonSerializer.Serialize(result) } } },
        });
    }

    private async Task<object> WidgetsAsync(string? q)
    {
        var cat = await _catalog.GetAsync(false, HttpContext.RequestAborted);
        var list = new List<object>();
        if (cat is JsonElement c && c.TryGetProperty("contributions", out var contrib)
            && contrib.TryGetProperty(PluginCatalog.Client, out var webui) && webui.TryGetProperty("widget", out var widgets))
        {
            var filter = (q ?? "").Trim().ToLowerInvariant();
            foreach (var w in widgets.EnumerateArray())
            {
                string S(string k) => w.TryGetProperty(k, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() ?? "" : "";
                var text = $"{S("id")} {S("label")} {S("module")} {S("help")}".ToLowerInvariant();
                if (filter.Length > 0 && !text.Contains(filter)) continue;
                var parameters = new Dictionary<string, string>();
                if (w.TryGetProperty("params", out var ps) && ps.ValueKind == JsonValueKind.Object)
                    foreach (var prop in ps.EnumerateObject())
                        parameters[prop.Name] = prop.Value.TryGetProperty("type", out var t) ? t.GetString() ?? "string" : "string";
                list.Add(new
                {
                    id = S("id"), label = S("label"), module = S("module"), help = S("help"),
                    sizes = w.TryGetProperty("sizes", out var sz) && sz.ValueKind == JsonValueKind.Array
                        ? sz.EnumerateArray().Select(x => x.GetString() ?? "").ToArray() : Array.Empty<string>(),
                    size = S("size"),
                    auto = w.TryGetProperty("auto", out var au) && au.ValueKind == JsonValueKind.True,
                    online = !w.TryGetProperty("online", out var on) || on.ValueKind != JsonValueKind.False,
                    @params = parameters,
                });
            }
        }
        return new { count = list.Count, widgets = list };
    }

    private async Task<object> DashboardsAsync()
    {
        var (status, payload) = await _hub.RouteRawAsync("themis", $"/api/settings/key/{DashboardsKey}", HttpMethod.Get,
            query: new Dictionary<string, string> { ["client"] = PluginCatalog.Client }, timeoutSeconds: 8,
            ct: HttpContext.RequestAborted);
        if (status >= 400 || payload.ValueKind != JsonValueKind.Object || !payload.TryGetProperty("value", out var value))
            return new { error = "impostazioni non raggiungibili", key = DashboardsKey };
        var node = JsonNode.Parse(value.GetRawText());
        var dashboards = node?["dashboards"] as JsonArray ?? [];
        return new
        {
            key = DashboardsKey,
            note = dashboards.Count == 0
                ? "Nessuna dashboard salvata: la Home mostra in automatico i widget 'auto'."
                : "Per cambiare proponi l'oggetto completo (settings_propose).",
            value = node,
        };
    }
}
