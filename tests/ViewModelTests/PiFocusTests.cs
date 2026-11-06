using System.Text.Json;
using Loupedeck.CodexMxPlugin;

internal static class PiFocusTests
{
    private const string PathId = "/home/user/.pi/sessions/chat ' π.jsonl";
    private const string NativeId = "native-pi-id";
    private const string TerminalId = "stable-pi-terminal";
    private const string ItermId = "12345678-1234-1234-1234-123456789abc";
    private static JsonElement Agent(string value = PathId, string kind = "path",
        string client = "pi", string terminal = TerminalId, string pane = "wPi:p3") =>
        JsonSerializer.SerializeToElement(new {
            agent = client, pane_id = pane, terminal_id = terminal, focused = true,
            agent_session = new { agent = client, kind, value }
        });

    public static async Task<int> Run()
    {
        int count = 0;
        void Check(bool value, string reason) { if (!value) throw new Exception(reason); count++; }
        foreach (bool remote in new[] { false, true })
        {
            var tile = new Tile("pi-key", "Worker", "WAITING", remote ? "cloud" : "local",
                Herdr: true, Client: "pi", SessionId: NativeId, SessionPath: PathId,
                HerdrSocket: remote ? "" : "/tmp/pi.sock", RemoteHost: remote ? "cloud" : null,
                Kind: "subagent", AgentRole: "frontier");
            var options = new HerdrFocusOptions();
            if (remote) options.RemoteBindings.Add(new() {
                Source = "cloud", SshTarget = "bound-cloud", ItermId = ItermId
            });
            else options.Bindings.Add(new() { SocketPath = "/tmp/pi.sock", ItermId = ItermId });
            var matching = Agent();
            var listed = new[] { Agent(NativeId, "id", "codex", pane: "wPi:p1"), matching };
            var current = matching;
            var calls = new List<string>();
            Task<JsonElement> Api(HerdrEndpoint endpoint, string method, object parameters, CancellationToken _)
            {
                Check(remote ? endpoint.Remote?.SshTarget == "bound-cloud" :
                               endpoint.Socket == "/tmp/pi.sock", "Pi uses the explicit endpoint binding");
                calls.Add(method);
                if (method == "agent.list")
                    return Task.FromResult(JsonSerializer.SerializeToElement(new { type = "agent_list", agents = listed }));
                Check(JsonSerializer.SerializeToElement(parameters).GetProperty("target").GetString() == "wPi:p3",
                      "Pi target is an opaque pane ID, not the tab index or session path");
                return Task.FromResult(JsonSerializer.SerializeToElement(new { type = "agent_info", agent = current }));
            }
            Task Select(string id, string tty, bool checkOnly, CancellationToken _)
            {
                Check(id == ItermId && tty == "", "Pi selects the bound iTerm UUID");
                calls.Add(checkOnly ? "iterm.check" : "iterm.select");
                return Task.CompletedTask;
            }
            Task<string> Focus(Tile? other = null) =>
                HerdrFocus.FocusAsync(other ?? tile, options, Api, Select, CancellationToken.None);
            async Task Reject(string reason, Tile? other = null)
            {
                calls.Clear();
                try { await Focus(other); }
                catch (InvalidOperationException error) when (error.Message.Contains(reason))
                { count++; return; }
                throw new Exception("Expected Pi focus rejection: " + reason);
            }
            Check(await Focus() == "wPi:p3", "Pi child matches its native session path");
            Check(calls.SequenceEqual(new[] { "agent.list", "iterm.check", "agent.get", "agent.focus", "iterm.select" }),
                  "Pi keeps every focus preflight and postcondition");
            Array.Reverse(listed);
            Check(await Focus() == "wPi:p3", "reordering list/tab positions cannot change the selected Pi session");
            listed = new[] { matching, matching };
            await Reject("More than one");
            Check(!calls.Contains("agent.focus"), "duplicate Pi sessions cannot focus arbitrarily");
            listed = new[] { Agent("/other/chat ' π.jsonl") };
            await Reject("no live Herdr pane");
            listed = new[] { Agent(PathId, client: "codex") };
            await Reject("no live Herdr pane");
            listed = new[] { matching };
            current = Agent("/sessions/replacement.jsonl");
            await Reject("changed occupants");
            Check(!calls.Contains("agent.focus"), "Pi session replacement is rechecked before focus");
            current = Agent(terminal: "replacement-terminal");
            await Reject("changed occupants");
            await Reject("Invalid Pi session path", tile with { SessionPath = "../relative" });
            current = matching;
            listed = new[] { Agent(NativeId, "id") };
            current = listed[0];
            Check(await Focus() == "wPi:p3", "Pi ID fallback requires an explicit native Herdr id reference");

            var display = DisplayOptions.Parse("""
                {"schema_version":1,"mode":"pet","pet":"cat",
                 "pet_rules":[{"location":"remote","pet":"pingu"},{"client":"claude","pet":"dario"}]}
                """);
            Check(PetSelection.For(tile, display) == (remote ? "pingu" : "cat"),
                  "existing source rules apply to Pi without changing Claude's pet");
            display.PetRules.Add(new() { Client = "pi", Pet = "clippit" });
            PetSelection.Validate(display);
            Check(PetSelection.For(tile, display) == "clippit", "Pi accepts a client-specific pet override");
            Check(tile.Header.StartsWith("Pi · "), "Pi captions identify the client");
            Check(DisplayPlan.Animation(tile.Status) == ("waiting", true), "Pi UI wait uses the waiting pet");
            display.UseChatNames = false;
            Check(DisplayPlan.Labels(tile with { FallbackName = "Agent launch name" }, display).Header.Contains("Agent launch name"),
                  "Pi saved names can be disabled without reloading Pi");
            display.NameOverrides[tile.Key] = "Custom button name";
            Check(DisplayPlan.Labels(tile, display).Header.Contains("Custom button name"),
                  "explicit Pi chat label overrides take priority");
        }
        return count;
    }
}
