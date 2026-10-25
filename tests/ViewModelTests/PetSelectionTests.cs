using System.Text.Json;
using Loupedeck.CodexMxPlugin;

internal static class PetSelectionTests
{
    public static int Run(string? contractPath = null)
    {
        int count = 0;
        void Check(bool result, string message)
        {
            if (!result) throw new Exception(message);
            count++;
        }
        void Reject(Action action, string message)
        {
            try { action(); }
            catch (Exception ex) when (ex is JsonException or InvalidDataException or IOException)
            { count++; return; }
            throw new Exception(message);
        }
        var options = DisplayOptions.Parse("""
            {"schema_version":1,"mode":"pet","pet":"clippit","pet_rules":[
              {"location":"remote","pet":"pingu"},
              {"client":"claude","pet":"leader-avatar"},
              {"location":"local","client":"claude","pet":"pingu"},
              {"host":"desktop","client":"kiro","pet":"leader-avatar"},
              {"key":"remote/desktop/chat","pet":"clippit"}
            ]}
            """);
        var local = new Tile("chat", "same name", "WORKING", "local");
        var remote = local with { Key = "remote/desktop/other", Host = "desktop", RemoteHost = "desktop" };
        Check(PetSelection.For(local, options) == "clippit", "default applies to unmatched chats");
        Check(PetSelection.For(remote, options) == "pingu", "remote location selects a different pet");
        Check(PetSelection.For(local with { Client = "claude" }, options) == "pingu",
              "local and client selectors combine, and the last matching rule wins");
        Check(PetSelection.For(remote with { Client = "claude" }, options) == "leader-avatar",
              "a remote Claude chat does not match the local Claude rule");
        Check(PetSelection.For(remote with { Client = "kiro" }, options) == "leader-avatar",
              "remote host and client can be configured together");
        Check(PetSelection.For(remote with { Key = "remote/desktop/chat", Client = "kiro" }, options) == "clippit",
              "a final chat override takes precedence over earlier broader rules");
        options.PetRules.Add(new() { Key = "chat", Pet = "leader-avatar" });
        Check(PetSelection.For(local, options) == "leader-avatar" &&
              PetSelection.For(remote with { Key = "remote/desktop/chat" }, options) == "clippit",
              "identical native session IDs on local and remote never share a key override");
        Check(PetSelection.For(local with { Key = "child", Kind = "subagent" }, options) == "clippit",
              "a child agent does not inherit its parent's key override");
        options.PetRules.Add(new() { Key = "child", Pet = "pingu" });
        Check(PetSelection.For(local with { Key = "child", Kind = "subagent" }, options) == "pingu",
              "child agents support their own pet");
        Check(PetSelection.For(local with { Key = "@client/claude/chat", Client = "claude" }, options) == "pingu",
              "client-qualified keys do not inherit another client's override");

        string a = "remote-with-a-long-name-alpha", b = "remote-with-a-long-name-beta";
        var state = new State { SchemaVersion = 1, Remotes = new()
        {
            [a] = new() { ReceivedAt = 100, Rows = new() { new() { Key = "a", Status = "READY", ValidUntil = 120 } } },
            [b] = new() { ReceivedAt = 100, Rows = new() { new() { Key = "b", Status = "READY", ValidUntil = 120 } } },
            ["local"] = new() { ReceivedAt = 100, Rows = new() { new() { Key = "c", Status = "READY", ValidUntil = 120 } } }
        } };
        options.PetRules = new() { new() { Location = "remote", Pet = "pingu" },
                                   new() { Host = a, Pet = "leader-avatar" } };
        var tiles = ViewModel.Tiles(state, 100);
        var tileA = tiles.Single(t => t.RemoteHost == a);
        var tileB = tiles.Single(t => t.RemoteHost == b);
        Check(tileA.Host == tileB.Host && PetSelection.For(tileA, options) == "leader-avatar" &&
              PetSelection.For(tileB, options) == "pingu", "host matching uses the full alias, not its truncated label");
        Check(PetSelection.For(tiles.Single(t => t.RemoteHost == "local"), options) == "pingu",
              "a remote alias named local remains a remote source");
        Check(PetSelection.For(local with { Host = "bridge" }, options) is null, "bridge diagnostics stay text");
        Check(PetSelection.For(remote with { Host = "bridge", RemoteHost = "bridge" }, options) == "pingu",
              "a remote host named bridge is not a diagnostic tile");
        options.Mode = "text";
        Check(PetSelection.For(remote, options) is null, "text mode bypasses pet rules");
        Check(DisplayOptions.Parse("{\"schema_version\":1}").PetRules.Count == 0, "legacy settings need no rules");

        foreach (string bad in new[]
        {
            "null", "{}", "[null]", "[{}]", """[{"pet":"pingu"}]""",
            """[{"pet":"pingu","clinet":"claude"}]""", """[{"pet":"../pingu","location":"remote"}]""",
            """[{"pet":"pingu","client":"unknown"}]""", """[{"pet":"pingu","location":"unknown"}]""",
            """[{"pet":"pingu","host":null}]""", """[{"pet":"pingu","key":"\n"}]""",
            """[{"pet":"pingu","host":"desktop","location":"local"}]""",
            JsonSerializer.Serialize(Enumerable.Repeat(new { pet = "pingu", location = "remote" }, 65)),
            JsonSerializer.Serialize(Enumerable.Range(0, 16).Select(i => new { pet = $"pet-{i}", key = $"{i}" })),
            JsonSerializer.Serialize(new[] { new { pet = "pingu", host = new string('x', 256) } }),
            JsonSerializer.Serialize(new[] { new { pet = "pingu", key = new string('x', 701) } })
        })
            Reject(() => DisplayOptions.Parse("{\"schema_version\":1,\"pet\":\"clippit\",\"pet_rules\":" + bad + "}"),
                   "invalid rule was accepted: " + bad);

        string root = Path.Combine(Path.GetTempPath(), "mx-pet-packs-" + Guid.NewGuid());
        try
        {
            const string revision = "0123456789abcdef";
            var manifest = new PetManifest { SchemaVersion = 1, Name = "fixture", FrameWidth = 1, FrameHeight = 1,
                Animations = new[] { "idle", "running", "waiting", "review", "failed" }
                    .ToDictionary(s => s, s => new[] { "idle-0.png" }) };
            byte[] png = Convert.FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jMosAAAAASUVORK5CYII=");
            string AddPack(string name, string rev, byte[] image)
            {
                string path = Path.Combine(root, "pets", name, rev);
                Directory.CreateDirectory(path);
                File.WriteAllText(Path.Combine(path, "manifest.json"), JsonSerializer.Serialize(manifest, ViewModel.Json));
                File.WriteAllBytes(Path.Combine(path, "idle-0.png"), image);
                return path;
            }
            string first = AddPack("clippit", revision, png);
            AddPack("pingu", revision, Convert.FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="));
            var clippit = PetPack.Load(root, "clippit");
            var pingu = PetPack.Load(root, "pingu");
            Check(clippit.Id == "clippit/" + revision && pingu.Id == "pingu/" + revision,
                  "short names resolve to separate canonical imported packs");
            Check(!clippit.Frames["idle-0.png"].SequenceEqual(pingu.Frames["idle-0.png"]),
                  "the same frame filename in different pets retains separate image bytes");
            Check(clippit.Pixels == 1 && clippit.Frames.Count == 1, "repeated manifest references load each frame once");
            AddPack("clippit", ".import-in-progress", png);
            Check(PetSelection.Resolve(root, "clippit") == clippit.Id, "temporary imports are ignored");
            AddPack("clippit", "fedcba9876543210", png);
            Reject(() => PetSelection.Resolve(root, "clippit"), "ambiguous short name accepted");
            Check(PetSelection.Resolve(root, clippit.Id) == clippit.Id, "a pinned revision disambiguates a name");
            Reject(() => PetPack.Load(root, pingu.Id, 0), "aggregate pixel budget ignored");
            Reject(() => PetPack.Load(root, "missing"), "missing pack accepted");
            Check(PetPack.Load(root, pingu.Id).Frames.Count == 1, "one missing pack does not corrupt another pack");
            Reject(() => PetSelection.Resolve(root, "../clippit"), "path traversal accepted");
            File.Delete(Path.Combine(first, "idle-0.png"));
            Reject(() => PetPack.Load(root, clippit.Id), "missing frame accepted");
            manifest.Animations["idle"] = new[] { "../outside.png" };
            File.WriteAllText(Path.Combine(first, "manifest.json"), JsonSerializer.Serialize(manifest, ViewModel.Json));
            Reject(() => PetPack.Load(root, clippit.Id), "unsafe manifest frame accepted");
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
        if (contractPath is not null)
        {
            var contract = DisplayOptions.Parse(File.ReadAllText(contractPath));
            Check(PetSelection.For(local, contract) == "clippit", "Python short-name default contract");
            Check(PetSelection.For(remote, contract) == "pingu", "Python remote rule contract");
            Check(PetSelection.For(remote with { Client = "claude" }, contract) == "leader-avatar/0123456789abcdef",
                  "Python combined selectors and pinned pet ID contract");
        }
        return count;
    }
}
