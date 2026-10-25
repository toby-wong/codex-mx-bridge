using System.Text.Json;
using Loupedeck.CodexMxPlugin;

internal static class DisplayTests
{
    public static int Run()
    {
        int count = 0;
        void Check(bool condition, string message)
        {
            if (!condition) throw new Exception(message);
            count++;
        }
        var tile = new Tile("chat-id", "project", "TOOL", "local", SessionId: "chat-id");
        var names = new Dictionary<string, string> { ["chat-id"] = "Named conversation" };
        var options = DisplayOptions.Parse("{\"schema_version\":1,\"mode\":\"text\"}");
        var labels = DisplayPlan.Labels(tile, options, names);
        Check(labels.Header == "Codex · local\nNamed conversation" && labels.Footer == "TOOL",
              "saved chat names and location/client labels are independent of status");
        options.UseChatNames = false;
        Check(DisplayPlan.Labels(tile, options, names).Header.EndsWith("\nproject"),
              "chat names can be disabled to retain the project label");
        options.NameOverrides["chat-id"] = "My chat";
        Check(DisplayPlan.Labels(tile, options, names).Header.EndsWith("\nMy chat"),
              "explicit names take priority and are keyed by chat identity");
        var remote = tile with { Key = "remote/desktop/chat-id", Host = "desktop" };
        Check(DisplayPlan.Labels(remote, options, names).Header == "Codex · remote: desktop\nproject",
              "local titles and overrides do not leak to a remote chat with the same ID");
        options.NameOverrides[remote.Key] = "Remote build";
        Check(DisplayPlan.Labels(remote, options, names).Header.EndsWith("\nRemote build"),
              "remote chats support explicit names");
        options.UseChatNames = true;
        Check(DisplayPlan.Labels(tile with { Key = "child", Kind = "subagent", Name = "reviewer" }, options, names)
            .Header.EndsWith("\n> reviewer"), "a child keeps its own label instead of its parent's chat title");
        Check(DisplayPlan.Labels(tile with { Key = "claude", Client = "claude" }, options, names)
            .Header == "Claude · local\nproject", "Codex's name catalog cannot rename another client");
        options.ShowStatus = false;
        labels = DisplayPlan.Labels(tile, options, names);
        Check(labels.Footer == "" && !labels.Text.Contains("TOOL"), "status text can be hidden");
        Check(DisplayPlan.Animation(tile.Status) == ("running", true), "hiding text retains the status pose");
        options.ShowName = options.ShowLocation = options.ShowClient = false;
        labels = DisplayPlan.Labels(tile, options, names);
        Check(labels.Text == "" && DisplayPlan.LabelHeights(labels, 96) == (0, 0),
              "pet-only display reclaims all label space");
        var diagnostic = DisplayPlan.Labels(new("error", "Check state", "READ ERROR", "bridge"), options, names);
        Check(diagnostic.Text.Contains("READ ERROR"), "diagnostics stay visible with labels disabled");
        var areas = DisplayPlan.LabelHeights(new("source\nname", "TOOL"), 32);
        Check(areas.Header + areas.Footer <= 24, "small images still reserve space for the pet");
        foreach (string invalid in new[]
        {
            "{\"schema_version\":1,\"show_status\":\"off\"}",
            "{\"schema_version\":1,\"name_overrides\":null}",
            "{\"schema_version\":1,\"name_overrides\":{\"chat\":\"\\n\"}}",
            JsonSerializer.Serialize(new { schema_version = 1, name_overrides = new Dictionary<string, string>
                { ["chat"] = new string('x', 81) } }),
            new string(' ', DisplayOptions.MaxBytes + 1)
        })
        {
            try { DisplayOptions.Parse(invalid); throw new Exception("Invalid labels accepted"); }
            catch (JsonException) { count++; }
        }
        var parsed = ChatNameIndex.Parse("""
            {"id":"chat-id","thread_name":"Old name","ignored":"SECRET"}
            invalid
            {"id":"chat-id","thread_name":"New name"}
            {"id":"unlabeled","title":"SECRET"}
            {"id":"bad\nid","thread_name":"Bad"}
            """);
        Check(parsed.Count == 1 && parsed["chat-id"] == "New name",
              "the name index uses only named identities, tolerates partial lines, and takes the latest rename");
        string folder = Path.Combine(Path.GetTempPath(), "mx-name-index-" + Guid.NewGuid());
        Directory.CreateDirectory(folder);
        try
        {
            string path = Path.Combine(folder, "session_index.jsonl");
            var index = new ChatNameIndex();
            Check(!index.Refresh(path) && index.Names.Count == 0, "missing name metadata is optional");
            File.WriteAllText(path, "{\"id\":\"chat-id\",\"thread_name\":\"First name\"}\n");
            Check(index.Refresh(path) && index.Names["chat-id"] == "First name", "name metadata loads");
            Check(!index.Refresh(path), "unchanged names do not continuously redraw");
            File.AppendAllText(path, "{\"id\":\"chat-id\",\"thread_name\":\"Changed while running\"}\n");
            Check(index.Refresh(path) && index.Names["chat-id"] == "Changed while running",
                  "a rename is reloaded without restarting the plugin");
            File.Delete(path);
            Check(index.Refresh(path) && index.Names.Count == 0, "deleted metadata returns to configured names");
            File.WriteAllText(path, new string(' ', 4 * 1024 * 1024 + 1));
            Check(!index.Refresh(path), "oversize optional metadata cannot stop display polling");
        }
        finally { Directory.Delete(folder, recursive: true); }
        return count;
    }
}
