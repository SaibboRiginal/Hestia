namespace Hestia.WebUI.Services;

using System.Net;

/// <summary>
/// Decides whether a request comes from the home network (no access token needed) or from outside
/// (Cloudflare tunnel → token required). SPEC docs/work/2026-10-11-webui-local-access.
///
/// Local only when ALL hold — anything doubtful needs the token:
/// 1. Themis <c>webui.auth.local_without_token</c> is on;
/// 2. no proxy/tunnel header. Cloudflare's edge always adds Cf-Connecting-Ip / Cf-Ray / Cdn-Loop and a
///    client cannot strip them, so only their ABSENCE grants access: forging one only adds the token;
/// 3. Host is not a public tunnel host (cloudflared forwards the tunnel hostname);
/// 4. the TCP peer is loopback/private. No forwarded-headers middleware runs, so it can't be forged.
/// Never port-forward 19015 on the router: external access goes through the tunnel only.
/// </summary>
public class LocalAccess
{
    private static readonly string[] ProxyHeaders =
    {
        "Cf-Connecting-Ip", "Cf-Connecting-Ipv6", "Cf-Ray", "Cf-Ipcountry", "Cf-Visitor", "Cf-Warp-Tag-Id",
        "Cdn-Loop", "True-Client-Ip", "X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto",
        "X-Real-Ip", "Forwarded",
    };

    private readonly WebUISettings _settings;
    private readonly PublicUrlService _publicUrl;

    public LocalAccess(WebUISettings settings, PublicUrlService publicUrl)
    {
        _settings = settings;
        _publicUrl = publicUrl;
    }

    /// <summary>True when the request may skip the access token (see class summary).</summary>
    public bool IsLocal(HttpContext? context) => Reason(context) == "local";

    /// <summary>"local", or why the token is required (for logs and /auth/access).</summary>
    public string Reason(HttpContext? context)
    {
        if (context is null) return "no_context";
        if (!_settings.LocalWithoutToken) return "setting_off";
        if (HasProxyHeaders(context.Request)) return "proxied";
        if (_publicUrl.IsPublicHost(context.Request.Host.Host)) return "public_host";
        if (!IsPrivate(context.Connection.RemoteIpAddress)) return "public_address";
        return "local";
    }

    /// <summary>Request went through Cloudflare or any reverse proxy.</summary>
    public static bool HasProxyHeaders(HttpRequest req) => ProxyHeaders.Any(h => req.Headers.ContainsKey(h));

    /// <summary>Loopback, RFC 1918 or IPv6 ULA/link-local address.</summary>
    public static bool IsPrivate(IPAddress? ip)
    {
        if (ip is null) return false;
        if (ip.IsIPv4MappedToIPv6) ip = ip.MapToIPv4();
        if (IPAddress.IsLoopback(ip)) return true;
        var b = ip.GetAddressBytes();
        if (b.Length == 4)
            return b[0] == 10 || (b[0] == 172 && b[1] >= 16 && b[1] <= 31) || (b[0] == 192 && b[1] == 168);
        return ip.IsIPv6LinkLocal || ip.IsIPv6UniqueLocal;
    }
}
