using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using Loupedeck.CodexMxPlugin;

internal static class SocketTests
{
    private static async Task Exchange(
        Func<NetworkStream, JsonElement, CancellationToken, Task> respond,
        Func<string, Task> request)
    {
        string folder = Path.Combine(Path.GetTempPath(), "mxf-" + Guid.NewGuid().ToString("N")[..8]);
        Directory.CreateDirectory(folder);
        string path = Path.Combine(folder, "s");
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        using var listener = new Socket(AddressFamily.Unix, SocketType.Stream, ProtocolType.Unspecified);
        listener.Bind(new UnixDomainSocketEndPoint(path));
        listener.Listen(1);
        var server = Task.Run(async () =>
        {
            using var peer = await listener.AcceptAsync(deadline.Token);
            using var stream = new NetworkStream(peer, ownsSocket: false);
            using var reader = new StreamReader(stream, leaveOpen: true);
            using var message = JsonDocument.Parse(await reader.ReadLineAsync(deadline.Token) ?? "");
            await respond(stream, message.RootElement, deadline.Token);
        });
        try { await request(path); }
        finally
        {
            deadline.Cancel();
            try { await server; }
            catch (Exception ex) when (ex is IOException or SocketException or OperationCanceledException) { }
            Directory.Delete(folder, recursive: true);
        }
    }

    public static async Task<int> Run()
    {
        if (OperatingSystem.IsWindows()) return 0; // Focus is a macOS feature; Unix sockets also run in Linux CI.
        int count = 0;
        async Task Rejected(string path, string message)
        {
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(2));
            try { await HerdrSocket.RequestAsync(path, "agent.list", new { }, deadline.Token); }
            catch (IOException ex) when (ex.Message.Contains(message, StringComparison.Ordinal))
            { count++; return; }
            throw new Exception("Expected socket rejection: " + message);
        }
        static Task Send(NetworkStream stream, object message, CancellationToken token) =>
            stream.WriteAsync(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(message) + "\n"), token).AsTask();

        await Exchange(async (stream, request, token) =>
        {
            byte[] data = Encoding.UTF8.GetBytes(JsonSerializer.Serialize(new
            {
                id = request.GetProperty("id").GetString(),
                result = new { type = "agent_list", agents = Array.Empty<object>() }
            }) + "\n");
            // Split the response inside its JSON and before the newline.
            await stream.WriteAsync(data.AsMemory(0, 3), token);
            await stream.WriteAsync(data.AsMemory(3, data.Length - 4), token);
            await stream.WriteAsync(data.AsMemory(data.Length - 1), token);
        }, async path =>
        {
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(2));
            var result = await HerdrSocket.RequestAsync(path, "agent.list", new { }, deadline.Token);
            if (HerdrFocus.Text(result, "type") != "agent_list") throw new Exception("Fragmented response failed");
            count++;
        });
        await Exchange((stream, _, token) =>
            Send(stream, new { id = "wrong-request", result = new { type = "agent_list" } }, token),
            path => Rejected(path, "response ID"));
        await Exchange((stream, request, token) =>
            Send(stream, new { id = request.GetProperty("id").GetString(),
                error = new { message = "private terminal data" } }, token),
            path => Rejected(path, "Herdr rejected agent.list"));
        await Exchange(async (stream, _, token) =>
            await stream.WriteAsync(new byte[1024 * 1024 + 1], token),
            path => Rejected(path, "exceeds 1 MiB"));
        await Exchange(async (stream, _, token) =>
            await stream.WriteAsync(Encoding.UTF8.GetBytes("{\"partial\":"), token),
            path => Rejected(path, "disconnected"));
        await Exchange((_, _, token) => Task.Delay(Timeout.Infinite, token), async path =>
        {
            using var deadline = new CancellationTokenSource(TimeSpan.FromMilliseconds(100));
            try { await HerdrSocket.RequestAsync(path, "agent.list", new { }, deadline.Token); }
            catch (OperationCanceledException) { count++; return; }
            throw new Exception("Unresponsive Herdr socket did not time out");
        });
        return count;
    }
}
