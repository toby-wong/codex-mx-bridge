using System.Diagnostics;
using System.Text.Json;

namespace Loupedeck.CodexMxPlugin;

internal sealed class HerdrTransport : IAsyncDisposable
{
    private string? _controlDirectory;
    private string? ControlPath => _controlDirectory is null ? null : Path.Combine(_controlDirectory, "%C");
    private readonly Dictionary<string, HerdrRemoteBinding> _connections = new(StringComparer.Ordinal);
    private readonly string _executable;

    internal HerdrTransport(string executable = "/usr/bin/ssh") => _executable = executable;

    internal Task<JsonElement> RequestAsync(HerdrEndpoint endpoint, string method, object parameters,
        CancellationToken cancellation)
    {
        if (endpoint.Remote is not { } remote)
            return HerdrSocket.RequestAsync(endpoint.Socket, method, parameters, cancellation);
        cancellation.ThrowIfCancellationRequested();
        if (OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("Herdr focus requires Unix SSH");
        if (_controlDirectory is null)
        {
            // Keep the expanded %C socket plus OpenSSH's temporary suffix below
            // macOS's Unix socket path limit, even with a long TMPDIR/state path.
            _controlDirectory = Path.Combine("/tmp", "mxh-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(_controlDirectory,
                UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
        }
        _connections[remote.SshTarget] = remote;
        return HerdrSsh.RequestAsync(remote, method, parameters, cancellation, _executable, ControlPath);
    }

    public async ValueTask DisposeAsync()
    {
        if (_controlDirectory is null) return;
        // Close only this action's masters. A short idle expiry also handles
        // process crashes or cancellation before a control socket was ready.
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(1));
        foreach (var binding in _connections.Values)
        {
            if (deadline.IsCancellationRequested) break;
            try { await HerdrSsh.CloseAsync(binding, ControlPath!, deadline.Token, _executable); }
            catch (Exception ex) when (ex is IOException or OperationCanceledException or System.ComponentModel.Win32Exception)
            { Trace.WriteLine(ex.Message); }
        }
        try { Directory.Delete(_controlDirectory, recursive: true); }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException) { Trace.WriteLine(ex.Message); }
        _controlDirectory = null;
        _connections.Clear();
    }
}

internal static class HerdrSsh
{
    // SSH receives one remote shell command. Quote every argument, including
    // server-supplied pane IDs; none is executable shell source.
    private static string Quote(string value) => "'" + value.Replace("'", "'\"'\"'") + "'";

    internal static ProcessStartInfo StartInfo(HerdrRemoteBinding binding, string method, object parameters,
        string executable = "/usr/bin/ssh", string? controlPath = null)
    {
        if (!binding.Valid()) throw new ArgumentException("Invalid remote Herdr binding");
        string action = method switch
        {
            "agent.list" => "list", "agent.get" => "get", "agent.focus" => "focus",
            _ => throw new ArgumentException("Unsupported Herdr focus operation")
        };
        var command = new List<string> { binding.HerdrPath };
        if (binding.RemoteSession.Length > 0)
            command.AddRange(new[] { "--session", binding.RemoteSession });
        command.AddRange(new[] { "agent", action });
        if (action != "list")
        {
            string target = HerdrFocus.Text(JsonSerializer.SerializeToElement(parameters), "target");
            if (target.Length is 0 or > 256 || target.StartsWith('-') || target.Any(char.IsControl))
                throw new ArgumentException("Invalid Herdr pane target");
            // Herdr 0.9.5 requires exactly one target and does not accept a
            // "--" separator. Reject option-like IDs and pass one quoted arg.
            command.Add(target);
        }
        var start = new ProcessStartInfo(executable)
        {
            UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true
        };
        foreach (string argument in new[] {
            "-n", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ClearAllForwardings=yes", "-o", "ForwardAgent=no", "-o", "ForwardX11=no",
            "-o", "PermitLocalCommand=no", "-o", "RemoteCommand=none",
            "-o", "ConnectTimeout=5", "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=1"
        }) start.ArgumentList.Add(argument);
        if (controlPath is not null)
            foreach (string argument in new[] {
                "-o", "ControlMaster=auto", "-o", "ControlPersist=10", "-o", "ControlPath=" + controlPath
            }) start.ArgumentList.Add(argument);
        start.ArgumentList.Add(binding.SshTarget);
        start.ArgumentList.Add("exec " + string.Join(" ", command.Select(Quote)));
        return start;
    }

    internal static async Task<JsonElement> RequestAsync(HerdrRemoteBinding binding, string method,
        object parameters, CancellationToken cancellation, string executable = "/usr/bin/ssh",
        string? controlPath = null)
    {
        var (exitCode, output) = await RunAsync(StartInfo(binding, method, parameters, executable, controlPath), cancellation);
        if (exitCode != 0)
            throw new IOException($"Remote Herdr {method} failed (SSH exit {exitCode}); " +
                "check SSH authentication, the Herdr path, and the running session.");
        using var document = JsonDocument.Parse(output);
        var response = document.RootElement;
        if (HerdrFocus.Text(response, "id") != "cli:" + method.Replace('.', ':'))
            throw new IOException("Remote Herdr response ID did not match the request");
        if (response.TryGetProperty("error", out _))
            throw new IOException($"Remote Herdr rejected {method}");
        if (!response.TryGetProperty("result", out var result) || result.ValueKind != JsonValueKind.Object)
            throw new JsonException("Missing remote Herdr response result");
        return result.Clone();
    }

    internal static async Task CloseAsync(HerdrRemoteBinding binding, string controlPath,
        CancellationToken cancellation, string executable)
    {
        var start = StartInfo(binding, "agent.list", new { }, executable, controlPath);
        start.ArgumentList.RemoveAt(start.ArgumentList.Count - 1); // No remote command for a control operation.
        start.ArgumentList.Insert(0, "-O");
        start.ArgumentList.Insert(1, "exit");
        await RunAsync(start, cancellation); // A missing/expired master is already closed.
    }

    private static async Task<(int ExitCode, byte[] Output)> RunAsync(ProcessStartInfo start, CancellationToken cancellation)
    {
        cancellation.ThrowIfCancellationRequested();
        using var process = Process.Start(start)
            ?? throw new IOException("Cannot start SSH for Herdr focus");
        using var reading = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        async Task<byte[]> Read(Stream stream, int limit, string label)
        {
            try
            {
                using var output = new MemoryStream();
                byte[] buffer = new byte[8192];
                while (true)
                {
                    int count = await stream.ReadAsync(buffer, reading.Token);
                    if (count == 0) return output.ToArray();
                    if (output.Length + count > limit)
                        throw new IOException($"Remote Herdr {label} exceeds {limit} bytes");
                    output.Write(buffer, 0, count);
                }
            }
            catch { reading.Cancel(); throw; }
        }
        var stdout = Read(process.StandardOutput.BaseStream, 1024 * 1024, "response");
        var stderr = Read(process.StandardError.BaseStream, 16384, "SSH error");
        try
        {
            await Task.WhenAll(stdout, stderr, process.WaitForExitAsync(reading.Token));
            return (process.ExitCode, await stdout);
        }
        catch
        {
            try { if (!process.HasExited) process.Kill(entireProcessTree: true); }
            catch (InvalidOperationException) when (process.HasExited) { }
            throw;
        }
    }
}
