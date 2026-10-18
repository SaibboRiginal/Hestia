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
        // Tools from Hestia's one MCP server (the same ones Oracle, Telegram and external AIs use).
        var commands = (await _hubClient.McpListToolsAsync("webui")).Select(HubClient.ToolAsCommand).ToList();
        return Ok(new { commands, count = commands.Count });
    }

    [HttpPost("execute")]
    public async Task<IActionResult> Execute([FromBody] CommandExecuteRequest req)
    {
        var commandName = (req.Command ?? "").Trim();
        if (string.IsNullOrEmpty(commandName))
            return BadRequest(new { ok = false, error = "command required" });

        var args = req.Args ?? new();
        var tool = (await _hubClient.McpListToolsAsync("webui"))
            .FirstOrDefault(t => t.TryGetProperty("name", out var n) && n.GetString() == commandName);
        if (tool.ValueKind != JsonValueKind.Object)
            return NotFound(new { ok = false, error = $"not found: {commandName}" });
        var cmd = HubClient.ToolAsCommand(tool);

        try
        {
            // Hestia-MCP fills the tool's path/templates and routes it through Hub.
            var (ok, result) = await _hubClient.McpCallToolAsync("webui", commandName, args, sessionId: null);
            if (!ok)
                return Ok(new { ok = false, error = result.ValueKind == JsonValueKind.String ? result.GetString() : result.ToString(), result });

            // oracle_natural commands: Oracle turns the raw payload into readable text
            // (same /api/format path Telegram uses).
            string? text = null;
            if (cmd["response_mode"] as string == "oracle_natural")
            {
                try
                {
                    var formatted = await _hubClient.RoutePostAsync("oracle", "/api/format", new
                    {
                        command = commandName,
                        payload = result,
                        response_prompt = cmd["response_prompt"] as string,
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
}

public record CommandExecuteRequest(string Command, Dictionary<string, object>? Args = null);
