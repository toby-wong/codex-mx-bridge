using System.Text.Json;
using System.Reflection;
using Loupedeck.CodexMxPlugin;

internal static class FocusTests
{
    private const string SocketPath = "/tmp/mx-herdr.sock";
    private const string ItermId = "12345678-1234-1234-1234-123456789abc";
    private const string SessionId = "codex-chat";
    private const string PaneId = "wZ:p3";

    private static JsonElement Agent(string session = SessionId, string terminal = "terminal-1",
        string kind = "id", string provider = "codex", bool selected = true) => JsonSerializer.SerializeToElement(new
        {
            pane_id = PaneId, terminal_id = terminal, agent = provider, focused = selected,
            agent_session = new { source = "herdr:codex", agent = provider, kind, value = session }
        });
    private static JsonElement Info(JsonElement agent) =>
        JsonSerializer.SerializeToElement(new { type = "agent_info", agent });

    public static async Task<int> Run()
    {
        int count = 0;
        void Check(bool value, string message)
        {
            if (!value) throw new Exception(message);
            count++;
        }
        async Task Reject(Func<Task> action, string message)
        {
            try { await action(); }
            catch (Exception ex) when (ex.Message.Contains(message, StringComparison.Ordinal))
            { count++; return; }
            throw new Exception("Expected rejection: " + message);
        }

        var assembly = typeof(FocusTests).Assembly;
        var inMemory = Assembly.Load(File.ReadAllBytes(assembly.Location));
        Check(string.IsNullOrEmpty(inMemory.Location), "reproduce Logi's in-memory assembly loading");
        string script = FocusScript.Read(inMemory);
        Check(script.Length > 0 && script == FocusScript.Read(assembly),
              "focus script is available without any assembly filesystem path");

        var tile = new Tile("chat", "Codex", "WORKING", "local", ItermId: "obsolete",
            Herdr: true, SessionId: SessionId, HerdrSocket: SocketPath);
        string config = JsonSerializer.Serialize(new
        {
            schema_version = 1,
            bindings = new[] { new { socket_path = SocketPath, iterm_id = ItermId } }
        });
        var options = HerdrFocusOptions.Parse(config);
        var calls = new List<string>();
        var listed = new[] { Agent() };
        var current = Agent();
        var focused = Agent();
        bool missingTerminal = false, focusError = false;
        Task<JsonElement> Api(HerdrEndpoint endpoint, string method, object parameters, CancellationToken cancellation)
        {
            Check(endpoint.Remote is null && endpoint.Socket == Path.GetFullPath(SocketPath),
                  "focus uses only the row's local socket");
            calls.Add(method);
            if (method == "agent.list")
                return Task.FromResult(JsonSerializer.SerializeToElement(new { type = "agent_list", agents = listed }));
            Check(JsonSerializer.SerializeToElement(parameters).GetProperty("target").GetString() == PaneId,
                  "live pane ID is passed as JSON data");
            if (method == "agent.focus" && focusError) throw new IOException("focus rejected");
            return Task.FromResult(Info(method == "agent.get" ? current : focused));
        }
        Task Terminal(string id, string tty, bool checkOnly, CancellationToken cancellation)
        {
            Check(id == ItermId && tty == "", "explicit UUID binding takes priority over inherited terminal data");
            calls.Add(checkOnly ? "iterm.check" : "iterm.select");
            if (missingTerminal) throw new IOException("terminal missing");
            return Task.CompletedTask;
        }
        Task<string> Focus(Tile? target = null) =>
            HerdrFocus.FocusAsync(target ?? tile, options, Api, Terminal, CancellationToken.None);

        Check(await Focus() == PaneId, "select current Herdr pane");
        Check(calls.SequenceEqual(new[] { "agent.list", "iterm.check", "agent.get", "agent.focus", "iterm.select" }),
              "validate terminal and current identity before Herdr focus, then foreground iTerm");

        calls.Clear();
        Check(await Focus(tile with { HerdrSocket = "" }) == PaneId,
              "legacy rows resolve their native chat through an explicit server binding");
        Check(calls.SequenceEqual(new[] { "agent.list", "iterm.check", "agent.get", "agent.focus", "iterm.select" }),
              "legacy lookup retains all identity and terminal checks");

        foreach (var agents in new[] { Array.Empty<JsonElement>(), new[] { Agent(kind: "path") },
                                      new[] { Agent(provider: "claude") }, new[] { Agent(session: "another-chat") } })
        {
            calls.Clear(); listed = agents;
            await Reject(() => Focus(), "no live Herdr pane");
            Check(calls.SequenceEqual(new[] { "agent.list" }), "no matching native session produces no focus");
        }
        listed = new[] { Agent(), Agent() }; calls.Clear();
        await Reject(() => Focus(), "More than one");
        Check(!calls.Contains("iterm.check"), "ambiguous session leaves terminals alone");
        listed = new[] { Agent() };

        foreach (var replaced in new[] { Agent(session: "replacement"), Agent(terminal: "replacement-terminal") })
        {
            current = replaced; calls.Clear();
            await Reject(() => Focus(), "changed occupants");
            Check(!calls.Contains("agent.focus") && !calls.Contains("iterm.select"), "reused pane never focused");
        }
        current = Agent(); missingTerminal = true; calls.Clear();
        await Reject(() => Focus(), "terminal missing");
        Check(!calls.Contains("agent.focus"), "missing Mac pane stops before Herdr mutation");
        missingTerminal = false; focusError = true; calls.Clear();
        await Reject(() => Focus(), "focus rejected");
        Check(!calls.Contains("iterm.select"), "failed Herdr focus does not activate a terminal");
        focusError = false;
        foreach (var unconfirmed in new[] { Agent(session: "replacement"), Agent(selected: false) })
        {
            focused = unconfirmed; calls.Clear();
            await Reject(() => Focus(), "could not confirm");
            Check(!calls.Contains("iterm.select"), "Herdr must confirm focus on the requested chat");
        }
        focused = Agent();

        foreach (var client in new[] { "claude", "kiro" })
        {
            calls.Clear();
            await Reject(() => Focus(tile with { Client = client }), "supports Codex sessions only");
            Check(calls.Count == 0, "another client's ID cannot select a Codex pane");
        }
        foreach (var invalid in new[] { tile with { Herdr = false }, tile with { Host = "linux" },
                                        tile with { HerdrSocket = "relative" }, tile with { SessionId = "" } })
        {
            calls.Clear();
            await Reject(() => Focus(invalid), "Herdr identity");
            Check(calls.Count == 0, "invalid or remote target does not access a socket");
        }
        calls.Clear();
        await Reject(() => HerdrFocus.FocusAsync(tile,
            HerdrFocusOptions.Parse("{\"schema_version\":1,\"bindings\":[]}"), Api, Terminal,
            CancellationToken.None), "Bind this Herdr session");
        Check(calls.Count == 0, "unbound socket never accessed");

        var secondSocket = "/tmp/mx-other-herdr.sock";
        var twoBindings = new HerdrFocusOptions { SchemaVersion = 1, Bindings = new()
        {
            new() { SocketPath = SocketPath, ItermId = ItermId },
            new() { SocketPath = secondSocket, ItermId = ItermId }
        }};
        var inspected = new List<string>();
        bool secondMatches = false, secondOffline = false;
        Task<JsonElement> AcrossServers(HerdrEndpoint endpoint, string method, object parameters, CancellationToken cancellation)
        {
            Check(method == "agent.list", "resolution alone never changes focus");
            string socket = endpoint.Socket;
            inspected.Add(socket);
            if (socket == secondSocket && secondOffline) throw new IOException("server offline");
            var agents = socket == SocketPath || secondMatches ? new[] { Agent() } : Array.Empty<JsonElement>();
            return Task.FromResult(JsonSerializer.SerializeToElement(new { type = "agent_list", agents }));
        }
        var legacy = tile with { HerdrSocket = "" };
        var resolved = await HerdrFocus.ResolveAsync(legacy, twoBindings, AcrossServers, CancellationToken.None);
        Check(resolved.Endpoint.Socket == SocketPath && inspected.Count == 2,
              "legacy resolution checks every configured server before choosing a unique match");
        secondMatches = true;
        await Reject(() => HerdrFocus.ResolveAsync(legacy, twoBindings, AcrossServers, CancellationToken.None),
                     "More than one");
        secondOffline = true;
        await Reject(() => HerdrFocus.ResolveAsync(legacy, twoBindings, AcrossServers, CancellationToken.None),
                     "server offline");
        inspected.Clear();
        resolved = await HerdrFocus.ResolveAsync(tile, twoBindings, AcrossServers, CancellationToken.None);
        Check(resolved.Endpoint.Socket == SocketPath && inspected.SequenceEqual(new[] { SocketPath }),
              "an explicit socket never falls back to a different server");

        foreach (string invalid in new[]
        {
            "{}", "{\"schema_version\":1}", "{\"schema_version\":2,\"bindings\":[]}", "{\"schema_version\":1,\"bindings\":[null]}",
            config.Replace(ItermId, "bad-id"), config.Replace(SocketPath, "relative.sock"),
            JsonSerializer.Serialize(new { schema_version = 1, bindings = new[] {
                new { socket_path = SocketPath, iterm_id = ItermId },
                new { socket_path = SocketPath, iterm_id = ItermId } } }),
            new string(' ', 65537)
        })
        {
            try { HerdrFocusOptions.Parse(invalid); }
            catch (JsonException) { count++; continue; }
            throw new Exception("Malformed focus configuration accepted");
        }
        return count;
    }

    public static async Task Probe(string socket)
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        var result = await HerdrSocket.RequestAsync(socket, "agent.list", new { }, deadline.Token);
        if (HerdrFocus.Text(result, "type") != "agent_list")
            throw new Exception("Unexpected live Herdr response");
        Console.WriteLine($"PASS: read-only Herdr socket probe ({result.GetProperty("agents").GetArrayLength()} agents)");
    }

    public static async Task ProbeMap(string statePath, string bindingsPath)
    {
        var state = ViewModel.Parse(File.ReadAllText(statePath));
        var options = HerdrFocusOptions.Parse(File.ReadAllText(bindingsPath));
        var tiles = ViewModel.Tiles(state, DateTimeOffset.UtcNow.ToUnixTimeSeconds());
        await using var transport = new HerdrTransport();
        for (int index = 0; index < tiles.Count; index++)
        {
            var tile = tiles[index];
            if (!tile.Herdr) continue;
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(8));
            try
            {
                var target = await HerdrFocus.ResolveAsync(tile, options, transport.RequestAsync, deadline.Token);
                var current = HerdrFocus.Agent(await transport.RequestAsync(target.Endpoint, "agent.get",
                    new { target = target.Pane }, deadline.Token));
                if (!HerdrFocus.Matches(current, tile.SessionId) ||
                    HerdrFocus.Text(current, "terminal_id") != target.Terminal ||
                    HerdrFocus.Text(current, "pane_id") != target.Pane)
                    throw new InvalidOperationException("Herdr pane changed occupants during the probe.");
                string server = target.Endpoint.Remote is { } remote
                    ? $"ssh={remote.SshTarget}; remote_session={remote.RemoteSession}" : $"socket={target.Endpoint.Socket}";
                Console.WriteLine($"MATCH slot={index + 1}; source={tile.RemoteHost ?? "local"}; session={tile.SessionId}; pane={target.Pane}; {server}");
            }
            catch (Exception ex)
            {
                Console.WriteLine($"UNAVAILABLE slot={index + 1}; session={tile.SessionId}; reason={ex.Message}");
            }
        }
    }

    public static async Task ProbeScript(string binary)
    {
        var assembly = Assembly.Load(File.ReadAllBytes(binary));
        if (!string.IsNullOrEmpty(assembly.Location) || FocusScript.Read(assembly).Length == 0)
            throw new Exception("Packaged plugin script cannot be loaded from memory");
        Console.WriteLine("PASS: packaged plugin focus script loads from an assembly with no filesystem location");
        if (OperatingSystem.IsMacOS())
        {
            // Exercise the actual packaged launcher using harmless AppleScript.
            // This checks stdin/argv handling without selecting any user window.
            const string probe = """
                on run argv
                    if (count of argv) is not 3 then error "Wrong argument count"
                    if item 1 of argv is not "focus-probe" then error "Wrong target"
                    if item 2 of argv is not "/dev/focus-probe" then error "Wrong tty"
                    if item 3 of argv is not "check" then error "Wrong mode"
                    return "ok"
                end run
                """;
            var dashboard = assembly.GetType("Loupedeck.CodexMxPlugin.Dashboard", throwOnError: true)!;
            var launch = dashboard.GetMethod("FocusIterm", BindingFlags.NonPublic | BindingFlags.Static)!;
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
            await (Task)launch.Invoke(null, new object[] {
                probe, "focus-probe", "/dev/focus-probe", true, deadline.Token })!;
            Console.WriteLine("PASS: packaged plugin passes AppleScript through stdin and focus arguments through argv");
        }
    }
}
