using System.Text.Json;
using Loupedeck.CodexMxPlugin;

internal static class RemoteFocusTests
{
    private const string Iterm = "12345678-1234-1234-1234-123456789abc";
    private const string OtherIterm = "87654321-4321-4321-4321-cba987654321";
    private const string Session = "native-chat";
    private static JsonElement Agent(string session = Session, bool focused = true) =>
        JsonSerializer.SerializeToElement(new
        {
            agent = "codex", agent_session = new { agent = "codex", kind = "id", value = session },
            pane_id = "w2:p3", terminal_id = "remote-terminal", focused
        });

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
            throw new Exception("Expected remote rejection: " + message);
        }
        const string source = "workstation-shared-prefix-a";
        var binding = new HerdrRemoteBinding { Source = source, SshTarget = "workbox",
            HerdrPath = "/home/user/.local/bin/herdr", ItermId = Iterm };
        var options = new HerdrFocusOptions { SchemaVersion = 1,
            Bindings = new() { new() { SocketPath = "/tmp/local.sock", ItermId = OtherIterm } },
            RemoteBindings = new() { binding } };
        var tile = new Tile("remote/" + source + "/chat", "Same name", "TOOL", ViewModel.Short(source),
            ItermId: "remote-injected", Tty: "/dev/tty-injected", Herdr: true, SessionId: Session,
            HerdrSocket: "/tmp/local.sock", RemoteHost: source);
        var calls = new List<string>();
        var sessions = new List<string>();
        string liveSession = Session, focusSession = Session;
        bool offline = false, missingTerminal = false, duplicate = false, namedMatches = false;
        Task<JsonElement> Api(HerdrEndpoint endpoint, string method, object parameters, CancellationToken token)
        {
            Check(endpoint.Socket == "" && endpoint.Remote is { SshTarget: "workbox", Source: source },
                  "only a local remote binding can select the SSH destination; no local socket fallback");
            var remote = endpoint.Remote!;
            calls.Add(method);
            sessions.Add(remote.RemoteSession);
            if (offline && remote.RemoteSession == "work") throw new IOException("remote unreachable");
            if (method == "agent.list")
            {
                var agents = remote.RemoteSession == "" || namedMatches ? new[] { Agent() } : Array.Empty<JsonElement>();
                if (duplicate) agents = new[] { Agent(), Agent() };
                return Task.FromResult(JsonSerializer.SerializeToElement(new { type = "agent_list", agents }));
            }
            Check(HerdrFocus.Text(JsonSerializer.SerializeToElement(parameters), "target") == "w2:p3",
                  "remote focus uses the live opaque pane ID");
            var agent = Agent(method == "agent.get" ? liveSession : focusSession);
            return Task.FromResult(JsonSerializer.SerializeToElement(new { type = "agent_info", agent }));
        }
        string expectedIterm = Iterm;
        Task Terminal(string id, string tty, bool check, CancellationToken token)
        {
            Check(id == expectedIterm && tty == "", "remote server metadata never chooses a Mac pane");
            calls.Add(check ? "iterm.check" : "iterm.select");
            if (missingTerminal) throw new IOException("terminal missing");
            return Task.CompletedTask;
        }
        Task Focus(Tile? selected = null) =>
            HerdrFocus.FocusAsync(selected ?? tile, options, Api, Terminal, CancellationToken.None);

        await Focus();
        Check(calls.SequenceEqual(new[] { "agent.list", "iterm.check", "agent.get", "agent.focus", "iterm.select" }),
              "remote focus retains native identity preflight and foregrounds only after confirmation");

        calls.Clear();
        await Reject(() => Focus(tile with { RemoteHost = "workstation-shared-prefix-b" }), "bind --remote");
        Check(calls.Count == 0, "hosts with the same shortened caption cannot acquire each other's bindings");
        await Reject(() => Focus(tile with { RemoteHost = "invalid;host" }), "Invalid remote Herdr source");
        Check(calls.Count == 0, "invalid source produces no SSH request");

        binding.Source = "local";
        Task<JsonElement> LocalNamedRemote(HerdrEndpoint endpoint, string method, object parameters, CancellationToken token)
        {
            Check(endpoint.Remote == binding && endpoint.Socket == "", "remote alias named local stays remote");
            return Task.FromResult(JsonSerializer.SerializeToElement(new { type = "agent_list", agents = new[] { Agent() } }));
        }
        await HerdrFocus.ResolveAsync(tile with { Host = "local", RemoteHost = "local" }, options,
                                     LocalNamedRemote, CancellationToken.None);
        binding.Source = source;

        calls.Clear(); liveSession = "replacement";
        await Reject(() => Focus(), "changed occupants");
        Check(!calls.Contains("agent.focus") && !calls.Contains("iterm.select"), "replaced remote pane is not selected");
        liveSession = Session; focusSession = "replacement"; calls.Clear();
        await Reject(() => Focus(), "could not confirm");
        Check(!calls.Contains("iterm.select"), "unconfirmed remote focus does not activate iTerm");
        focusSession = Session; missingTerminal = true; calls.Clear();
        await Reject(() => Focus(), "terminal missing");
        Check(!calls.Contains("agent.focus"), "closed Mac tab stops before the remote mutation");
        missingTerminal = false; duplicate = true; calls.Clear();
        await Reject(() => Focus(), "More than one");
        Check(!calls.Contains("iterm.check"), "duplicate native remote identity fails before any focus");
        duplicate = false;
        foreach (string client in new[] { "claude", "kiro" })
        {
            calls.Clear();
            await Reject(() => Focus(tile with { Client = client }), "supports Codex sessions only");
            Check(calls.Count == 0, "a different remote client cannot impersonate a Codex session");
        }

        options.RemoteBindings.Add(new() { Source = source, SshTarget = "workbox",
            RemoteSession = "work", ItermId = OtherIterm });
        calls.Clear(); sessions.Clear();
        await Focus();
        Check(sessions.SequenceEqual(new[] { "", "work", "", "" }),
              "all bound sessions of a source are searched; get and focus stay on the unique matching session");
        namedMatches = true;
        await Reject(() => Focus(), "More than one");
        namedMatches = false; offline = true; calls.Clear();
        await Reject(() => Focus(), "remote unreachable");
        Check(!calls.Contains("agent.focus") && !calls.Contains("iterm.select"),
              "an unreachable bound session cannot conceal an ambiguous identity");
        offline = false;

        // Re-reading the same file on the next press changes the Mac target.
        options.RemoteBindings.RemoveAt(1);
        binding.ItermId = OtherIterm;
        options = HerdrFocusOptions.Parse(JsonSerializer.Serialize(options, ViewModel.Json));
        expectedIterm = OtherIterm;
        await Focus();

        string valid = JsonSerializer.Serialize(options, ViewModel.Json);
        foreach (string invalid in new[]
        {
            valid.Replace("\"remote_bindings\":[", "\"remote_bindings\":null,\"ignored\":["),
            valid.Replace("\"ssh_target\":\"workbox\"", "\"ssh_target\":\"-oProxyCommand=bad\""),
            valid.Replace("\"source\":\"" + source + "\"", "\"source\":\"bad/source\""),
            valid.Replace("\"herdr_path\":\"/home/user/.local/bin/herdr\"", "\"herdr_path\":\"herdr --remote other\""),
            valid.Replace("\"remote_session\":\"\"", "\"remote_session\":\"../other\""),
            valid.Replace("\"remote_session\":\"\"", "\"remote_session\":null"),
            valid.Replace(OtherIterm, "invalid-uuid"),
            "{\"schema_version\":1,\"bindings\":[],\"remote_bindings\":[null]}",
            JsonSerializer.Serialize(new { schema_version = 1, bindings = Array.Empty<object>(),
                remote_bindings = new[] { binding, binding } }, ViewModel.Json),
            JsonSerializer.Serialize(new { schema_version = 1, bindings = Array.Empty<object>(),
                remote_bindings = Enumerable.Range(0, 17).Select(i => new HerdrRemoteBinding
                    { Source = $"host-{i}", SshTarget = "workbox", ItermId = Iterm }) }, ViewModel.Json)
        })
        {
            try { HerdrFocusOptions.Parse(invalid); }
            catch (JsonException) { count++; continue; }
            throw new Exception("Malformed remote focus configuration accepted");
        }
        Check(HerdrFocusOptions.Parse("{\"schema_version\":1,\"bindings\":[]}").RemoteBindings.Count == 0,
              "legacy binding files remain compatible");
        return count;
    }
}
