namespace Hestia.WebUI.Controllers;

using Microsoft.AspNetCore.Mvc;
using Hestia.WebUI.Services;

[ApiController]
[Route("api/webui/documents")]
public class FilesController : ControllerBase
{
    private readonly HubClient _hubClient;
    private readonly ILogger<FilesController> _logger;

    public FilesController(HubClient hubClient, ILogger<FilesController> logger)
    {
        _hubClient = hubClient;
        _logger = logger;
    }

    [HttpGet]
    public async Task<IActionResult> List()
    {
        try
        {
            var result = await _hubClient.RouteGetAsync("archive", "/api/documents");
            return Ok(result);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "event=webui_documents_list_failed");
            return Ok(new { documents = Array.Empty<object>(), count = 0 });
        }
    }

    [HttpDelete("{documentId}")]
    public async Task<IActionResult> Delete(string documentId)
    {
        try
        {
            await _hubClient.RouteDeleteAsync("archive", $"/api/documents/{documentId}");
            _logger.LogInformation("event=webui_document_deleted id={Id}", documentId);
            return Ok(new { ok = true, document_id = documentId });
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "event=webui_document_delete_failed id={Id}", documentId);
            return StatusCode(500, new { detail = ex.Message });
        }
    }
}
