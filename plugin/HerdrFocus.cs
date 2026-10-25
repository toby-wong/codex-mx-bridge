using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

namespace Loupedeck.CodexMxPlugin;

public sealed class HerdrBinding
{
    public string SocketPath { get; set; } = "";
    public string ItermId { get; set; } = "";
}

public sealed class HerdrRemoteBinding
{
    public string Source { get; set; } = "";
    public string SshTarget { get; set; } = "";
    public string HerdrPath { get; set; } = "herdr";
    public string RemoteSession { get; set; } = "";
    public string ItermId { get; set; } = "";

    internal bool Valid() =>
        HerdrFocusOptions.ValidName(Source) &&
        SshTarget is not null && Regex.IsMatch(SshTarget, @"\A[A-Za-z0-9][A-Za-z0-9_.@-]{0,254}\z") &&
        (HerdrPath == "herdr" || HerdrFocusOptions.ValidSocket(HerdrPath)) &&
        (RemoteSession == "" || HerdrFocusOptions.ValidName(RemoteSession)) &&
        Guid.TryParseExact(ItermId, "D", out _);
}

public sealed class HerdrFocusOptions
{
    public int SchemaVersion { get; set; }
    [JsonRequired]
    public List<HerdrBinding> Bindings { get; set; } = new();
    public List<HerdrRemoteBinding> RemoteBindings { get; set; } = new();

    public static HerdrFocusOptions Parse(string text)
    {
        if (Encoding.UTF8.GetByteCount(text) > 65536)
            throw new JsonException("Herdr focus configuration exceeds 64 KiB");
        var value = JsonSerializer.Deserialize<HerdrFocusOptions>(text, ViewModel.Json);
        if (value?.SchemaVersion != 1 || value.Bindings is null || value.Bindings.Count > 16 ||
            value.RemoteBindings is null || value.RemoteBindings.Count > 16)
            throw new JsonException("Invalid Herdr focus configuration");
        var sockets = new HashSet<string>(StringComparer.Ordinal);
        foreach (var binding in value.Bindings)
        {
            if (binding is null || !ValidSocket(binding.SocketPath) ||
                !Guid.TryParseExact(binding.ItermId, "D", out _) ||
                !sockets.Add(Path.GetFullPath(binding.SocketPath)))
                throw new JsonException("Invalid or duplicate Herdr terminal binding");
        }
        var remotes = new HashSet<(string, string)>();
        foreach (var binding in value.RemoteBindings)
        {
            if (binding is null || !binding.Valid() || !remotes.Add((binding.Source, binding.RemoteSession)))
                throw new JsonException("Invalid or duplicate remote Herdr terminal binding");
        }
        return value;
    }

    public static bool ValidSocket(string? path) => path is { Length: > 1 and <= 512 } &&
        path.StartsWith('/') && !path.Any(char.IsControl);

    internal static bool ValidName(string? name) => name is not null &&
        Regex.IsMatch(name, @"\A[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\z");
}

internal sealed record HerdrEndpoint(string ItermId, string Socket = "", HerdrRemoteBinding? Remote = null);

internal delegate Task<JsonElement> HerdrRequest(HerdrEndpoint endpoint, string method, object parameters,
                                               CancellationToken cancellation);
internal delegate Task ItermSelect(string id, string tty, bool checkOnly, CancellationToken cancellation);

internal sealed record HerdrFocusTarget(HerdrEndpoint Endpoint, string Pane, string Terminal);

internal static class HerdrFocus
{
    internal static string Text(JsonElement value, string key) =>
        value.ValueKind == JsonValueKind.Object && value.TryGetProperty(key, out var child) &&
        child.ValueKind == JsonValueKind.String ? child.GetString()! : "";

    internal static bool Matches(JsonElement agent, string session) =>
        Text(agent, "agent") == "codex" && agent.TryGetProperty("agent_session", out var identity) &&
        Text(identity, "agent") == "codex" && Text(identity, "kind") == "id" &&
        Text(identity, "value") == session;

    internal static JsonElement Agent(JsonElement result)
    {
        if (Text(result, "type") != "agent_info" || !result.TryGetProperty("agent", out var agent) ||
            agent.ValueKind != JsonValueKind.Object)
            throw new JsonException("Unsupported Herdr agent response");
        return agent;
    }

    internal static async Task<HerdrFocusTarget> ResolveAsync(Tile tile, HerdrFocusOptions options,
        HerdrRequest request, CancellationToken cancellation)
    {
        // Herdr matching below is verified only for Codex's native identity.
        // Another client's session ID must never select a matching Codex pane.
        if (tile.Client != "codex")
            throw new InvalidOperationException("Herdr button focus currently supports Codex sessions only.");
        if (!tile.Herdr || string.IsNullOrEmpty(tile.SessionId))
            throw new InvalidOperationException("No Herdr identity; wait for a hook from the updated bridge.");
        HerdrEndpoint[] endpoints;
        if (tile.RemoteHost is not null)
        {
            // Remote data supplies identity only. The full collector alias selects
            // explicitly configured SSH/session/outer-terminal authority on this Mac.
            if (!HerdrFocusOptions.ValidName(tile.RemoteHost))
                throw new InvalidOperationException("Invalid remote Herdr source.");
            endpoints = options.RemoteBindings.Where(b => b.Source == tile.RemoteHost)
                .Select(b => new HerdrEndpoint(b.ItermId, Remote: b)).ToArray();
            if (endpoints.Length == 0)
                throw new InvalidOperationException(
                    $"Bind this remote Herdr source with codex-mx herdr-focus bind --remote {tile.RemoteHost}.");
        }
        else
        {
            if (tile.Host != "local" ||
                (tile.HerdrSocket.Length > 0 && !HerdrFocusOptions.ValidSocket(tile.HerdrSocket)))
                throw new InvalidOperationException("No local Herdr identity; wait for a hook from the updated bridge.");
            // Older clients can keep socket-less rows. Search only bound local
            // servers and require one native identity across the complete search.
            endpoints = options.Bindings.Where(b => tile.HerdrSocket.Length == 0 ||
                Path.GetFullPath(b.SocketPath) == Path.GetFullPath(tile.HerdrSocket))
                .Select(b => new HerdrEndpoint(b.ItermId, Path.GetFullPath(b.SocketPath))).ToArray();
            if (endpoints.Length == 0)
                throw new InvalidOperationException("Bind this Herdr session with codex-mx herdr-focus bind.");
        }
        var matches = new List<HerdrFocusTarget>();
        foreach (var endpoint in endpoints)
        {
            var list = await request(endpoint, "agent.list", new { }, cancellation);
            if (Text(list, "type") != "agent_list" || !list.TryGetProperty("agents", out var agents) ||
                agents.ValueKind != JsonValueKind.Array)
                throw new JsonException("Unsupported Herdr agent list");
            foreach (var agent in agents.EnumerateArray().Where(a => Matches(a, tile.SessionId)))
            {
                string pane = Text(agent, "pane_id"), terminalId = Text(agent, "terminal_id");
                if (pane.Length == 0 || terminalId.Length == 0)
                    throw new JsonException("Herdr did not report a pane and terminal identity");
                matches.Add(new(endpoint, pane, terminalId));
            }
        }
        if (matches.Count != 1)
            throw new InvalidOperationException(matches.Count == 0
                ? "This Codex session has no live Herdr pane."
                : "More than one Herdr pane reports this Codex session.");
        return matches[0];
    }

    public static async Task<string> FocusAsync(Tile tile, HerdrFocusOptions options,
        HerdrRequest request, ItermSelect terminal, CancellationToken cancellation)
    {
        var target = await ResolveAsync(tile, options, request, cancellation);
        var (endpoint, pane, terminalId) = target;

        // Fail before changing Herdr if the mapped Mac pane is gone or permission is denied.
        await terminal(endpoint.ItermId, "", true, cancellation);
        var current = Agent(await request(endpoint, "agent.get", new { target = pane }, cancellation));
        if (!Matches(current, tile.SessionId) || Text(current, "terminal_id") != terminalId ||
            Text(current, "pane_id") != pane)
            throw new InvalidOperationException("Herdr pane changed occupants; press again to refresh.");
        var focused = Agent(await request(endpoint, "agent.focus", new { target = pane }, cancellation));
        if (!Matches(focused, tile.SessionId) || Text(focused, "terminal_id") != terminalId ||
            Text(focused, "pane_id") != pane || !focused.TryGetProperty("focused", out var selected) ||
            selected.ValueKind != JsonValueKind.True)
            throw new InvalidOperationException("Herdr could not confirm the selected Codex session.");
        await terminal(endpoint.ItermId, "", false, cancellation);
        return pane;
    }
}

internal static class HerdrSocket
{
    private const int MaxResponse = 1024 * 1024;

    public static async Task<JsonElement> RequestAsync(string path, string method, object parameters,
                                                       CancellationToken cancellation)
    {
        if (method is not ("agent.list" or "agent.get" or "agent.focus"))
            throw new ArgumentException("Unsupported Herdr focus operation");
        using var socket = new Socket(AddressFamily.Unix, SocketType.Stream, ProtocolType.Unspecified);
        await socket.ConnectAsync(new UnixDomainSocketEndPoint(path), cancellation);
        using var stream = new NetworkStream(socket, ownsSocket: false);
        string id = Guid.NewGuid().ToString("D");
        byte[] request = JsonSerializer.SerializeToUtf8Bytes(new { id, method, @params = parameters });
        await stream.WriteAsync(request, cancellation);
        await stream.WriteAsync(new byte[] { (byte)'\n' }, cancellation);
        using var output = new MemoryStream();
        byte[] buffer = new byte[8192];
        while (true)
        {
            int count = await stream.ReadAsync(buffer, cancellation);
            if (count == 0) throw new IOException("Herdr disconnected before replying");
            int newline = Array.IndexOf(buffer, (byte)'\n', 0, count);
            int length = newline < 0 ? count : newline;
            if (output.Length + length > MaxResponse)
                throw new IOException("Herdr response exceeds 1 MiB");
            output.Write(buffer, 0, length);
            if (newline >= 0) break;
        }
        using var document = JsonDocument.Parse(output.ToArray());
        var response = document.RootElement;
        if (HerdrFocus.Text(response, "id") != id)
            throw new IOException("Herdr response ID did not match the request");
        if (response.TryGetProperty("error", out _))
            throw new IOException($"Herdr rejected {method}");
        if (!response.TryGetProperty("result", out var result) || result.ValueKind != JsonValueKind.Object)
            throw new JsonException("Missing Herdr response result");
        return result.Clone();
    }
}
