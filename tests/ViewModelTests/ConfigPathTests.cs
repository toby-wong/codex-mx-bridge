using System.Text.Json;
using Loupedeck.CodexMxPlugin;

internal static class ConfigPathTests
{
    public static int Run()
    {
        int count = 0;
        void Check(bool condition, string message)
        {
            if (!condition) throw new Exception(message);
            count++;
        }
        string home = Path.Combine(Path.GetTempPath(), "mx-config-" + Guid.NewGuid());
        string state = Path.Combine(home, ".local", "state", "codex-mx-bridge");
        string preferred = Path.Combine(home, ".config", "codex-mx-bridge", "display.json");
        string legacy = Path.Combine(state, "display.json");
        Directory.CreateDirectory(state);
        try
        {
            Check(DisplayPaths.Preferred(state, home) == preferred,
                  "normal display config belongs in the home config directory");
            Check(DisplayPaths.Preferred(state + Path.DirectorySeparatorChar, home) == preferred,
                  "a trailing separator does not change default directory selection");
            Check(DisplayPaths.ReadLocation(state, home) == preferred,
                  "a fresh installation chooses the preferred location");
            File.WriteAllText(legacy, "{\"schema_version\":1,\"chat_view\":\"recent\"}");
            Check(DisplayPaths.ReadLocation(state, home) == legacy, "existing installations retain legacy settings");
            Directory.CreateDirectory(Path.GetDirectoryName(preferred)!);
            File.WriteAllText(preferred, "{\"schema_version\":1,\"chat_view\":\"newest\"}");
            Check(DisplayOptions.Parse(File.ReadAllText(DisplayPaths.ReadLocation(state, home))).ChatView == "newest",
                  "the new location has precedence when both files exist");
            File.WriteAllText(preferred, "invalid");
            Check(DisplayPaths.ReadLocation(state, home) == preferred,
                  "an invalid preferred config is not silently replaced by old preferences");
            try
            {
                DisplayOptions.Parse(File.ReadAllText(DisplayPaths.ReadLocation(state, home)));
                throw new Exception("Invalid preferred settings were accepted");
            }
            catch (JsonException) { count++; }
            File.Delete(preferred);
            Check(DisplayPaths.ReadLocation(state, home) == legacy, "legacy rollback remains available");
            string isolated = Path.Combine(home, "isolated-state");
            Check(DisplayPaths.Preferred(isolated, home) == Path.Combine(isolated, "display.json") &&
                  DisplayPaths.ReadLocation(isolated, home) == Path.Combine(isolated, "display.json"),
                  "a custom state root cannot consume default display preferences");
        }
        finally { Directory.Delete(home, true); }
        return count;
    }
}
