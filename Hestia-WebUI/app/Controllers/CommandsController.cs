namespace Hestia.WebUI.Controllers;

using System.Text.Json;
using Microsoft.AspNetCore.Mvc;
using Hestia.WebUI.Services;

[ApiController]
[Route("api/webui/commands")]
public class CommandsController : ControllerBase
{
    private readonly HubClient _hubClient;
    private readonly SessionManager _sessionManager;
    private readonly ILogger<CommandsController> _logger;

    public CommandsController(HubClient hubClient, SessionManager sessionManager, ILogger<CommandsController> logger)
    {
        _hubClient = hubClient;
        _sessionManager = sessionManager;
        _logger = logger;
    }

    [HttpGet]
    public async Task<IActionResult> List()
    {
        var hubCommands = await _hubClient.DiscoverCommandsAsync(client: "ui");
        // Return Hub commands directly as JSON — they already have the right shape
        return Ok(new { commands = hubCommands, count = hubCommands.Count });
    }

    [HttpPost("execute")]
    public async Task<IActionResult> Execute([FromBody] CommandExecuteRequest req)
    {
        var commandName = (req.Command ?? "").Trim().ToLowerInvariant();
        if (string.IsNullOrEmpty(commandName))
            return BadRequest(new { ok = false, error = "command required" });

        var args = req.Args ?? new();
        var commands = await _hubClient.DiscoverCommandsAsync(client: "ui");

        JsonElement? cmd = null;
        foreach (var c in commands)
            if (c.TryGetProperty("command", out var cn) && cn.GetString() == commandName)
            { cmd = c; break; }

        if (cmd is null)
            return NotFound(new { ok = false, error = $"not found: {commandName}" });

        try
        {
            var svc = cmd.Value.GetProperty("service").GetString() ?? "";
            var method = cmd.Value.GetProperty("method").GetString() ?? "GET";
            var path = cmd.Value.GetProperty("path").GetString() ?? "";
            var resolved = ResolveTemplate(path, args);

            JsonElement result = method.ToUpperInvariant() switch
            {
                "GET" => await _hubClient.RouteGetAsync(svc, resolved),
                "POST" => await _hubClient.RoutePostAsync(svc, resolved, args),
                "PUT" => await _hubClient.RoutePutAsync(svc, resolved, args),
                "DELETE" => await _hubClient.RouteDeleteAsync(svc, resolved),
                _ => throw new InvalidOperationException($"unsupported: {method}")
            };

            // oracle_natural commands: Oracle turns the raw payload into readable text
            // (same /api/format path Telegram uses).
            string? text = null;
            var responseMode = cmd.Value.TryGetProperty("response_mode", out var rm) ? rm.GetString() : "";
            if (responseMode == "oracle_natural")
            {
                try
                {
                    var prompt = cmd.Value.TryGetProperty("response_prompt", out var rp) ? rp.GetString() : null;
                    var formatted = await _hubClient.RoutePostAsync("oracle", "/api/format", new
                    {
                        command = commandName,
                        payload = result,
                        response_prompt = prompt,
                        client_instructions = _sessionManager.BuildClientInstructions(),
                        client = "webui",
                    }, timeoutSeconds: 60);
                    if (formatted.TryGetProperty("text", out var t)) text = t.GetString();
                }
                catch (Exception fex)
                {
                    _logger.LogWarning(fex, "event=webui_command_format_failed cmd={Cmd}", commandName);
                }
            }

            return Ok(new { ok = true, result, text });
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "cmd execute failed {Cmd}", commandName);
            return Ok(new { ok = false, error = ex.Message });
        }
    }

    private static string ResolveTemplate(string t, Dictionary<string, object> args)
    {
        // Hub command paths use {name} or $name placeholders (legacy: $arg.name).
        foreach (var (k, v) in args)
        {
            var val = Uri.EscapeDataString(v?.ToString() ?? "");
            t = t.Replace($"$arg.{k}", val).Replace($"{{{k}}}", val).Replace($"${k}", val);
        }
        return t;
    }
}

public record CommandExecuteRequest(string Command, Dictionary<string, object>? Args = null);
