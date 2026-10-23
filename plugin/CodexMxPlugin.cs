using System.Diagnostics;

namespace Loupedeck.CodexMxPlugin;

// Loupedeck is the namespace used by the official Logitech Actions C# SDK.
public sealed class CodexMxPlugin : Plugin
{
    public override bool UsesApplicationApiOnly => true;
    public override bool HasNoApplication => true;
    private CancellationTokenSource? _stop;
    private Task? _poll;
    public override void Load()
    {
        _stop = new();
        var token = _stop.Token;
        _poll = Task.Run(async () =>
        {
            while (!token.IsCancellationRequested)
            {
                Dashboard.Refresh();
                try { await Task.Delay(500, token); }
                catch (OperationCanceledException) { break; }
            }
        }, token);
    }
    public override void Unload()
    {
        _stop?.Cancel();
        try { _poll?.Wait(TimeSpan.FromSeconds(2)); } catch (AggregateException) { }
        _stop?.Dispose();
        _stop = null;
    }
}

public sealed class CodexMxApplication : ClientApplication
{
    protected override string GetProcessName() => "iTerm2";
    protected override string GetBundleName() => "com.googlecode.iterm2";
}

internal static class Dashboard
{
    private static readonly object Gate = new();
    private static List<Tile> _tiles = new();
    private static string _fingerprint = "";
    private static int _page;
    private static string _focusError = "";
    private static readonly string Home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
    public static event Action? Changed;
    public static string StatePath => Path.Combine(Environment.GetEnvironmentVariable("MX_CODEX_STATE_DIR") ??
        Path.Combine(Home, ".local", "state", "codex-mx-bridge"), "state.json");
    public static void Refresh()
    {
        List<Tile> tiles;
        try
        {
            var file = new FileInfo(StatePath);
            if (file.Length > 4 * 1024 * 1024) throw new InvalidDataException("Oversize state");
            tiles = ViewModel.Tiles(ViewModel.Parse(File.ReadAllText(StatePath)), DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0);
        }
        catch (FileNotFoundException) { tiles = new() { new("missing", "Install hooks", "NO DATA", "bridge") }; }
        catch (DirectoryNotFoundException) { tiles = new() { new("missing", "Install hooks", "NO DATA", "bridge") }; }
        catch (Exception ex) when (ex is IOException or System.Text.Json.JsonException or UnauthorizedAccessException)
        { tiles = new() { new("error", "Check state", "READ ERROR", "bridge") }; }
        lock (Gate)
        {
            var fingerprint = System.Text.Json.JsonSerializer.Serialize(tiles);
            if (fingerprint == _fingerprint) return;
            _fingerprint = fingerprint;
            _tiles = tiles;
            _page = ViewModel.WrapPage(_page, _tiles.Count);
        }
        Notify();
    }
    private static void Notify()
    {
        // SDK redraw callbacks must never kill the polling task.
        foreach (Action callback in Changed?.GetInvocationList() ?? Array.Empty<Delegate>())
            try { callback(); } catch (Exception ex) { Trace.WriteLine(ex.Message); }
    }
    public static Tile? Get(int slot)
    {
        lock (Gate)
        {
            int i = _page * 9 + slot;
            return i >= 0 && i < _tiles.Count ? _tiles[i] : null;
        }
    }
    public static string PageText { get { lock (Gate) return $"{_page + 1}/{ViewModel.PageCount(_tiles.Count)}"; } }
    public static void Move(int diff)
    {
        lock (Gate) _page = ViewModel.WrapPage(_page + Math.Sign(diff), _tiles.Count);
        Notify();
    }
    public static void Focus(Tile? tile)
    {
        if (tile is null) return;
        _ = Task.Run(() =>
        {
            string error = "";
            try
            {
                if (tile.ItermId.Length == 0 && tile.Tty.Length == 0)
                    throw new InvalidOperationException("No direct iTerm target; Herdr/remote pane focus is not implemented.");
                var script = Path.Combine(Path.GetDirectoryName(typeof(CodexMxPlugin).Assembly.Location)!, "..", "focus.applescript");
                var start = new ProcessStartInfo("/usr/bin/osascript") { UseShellExecute = false, RedirectStandardError = true, RedirectStandardOutput = true };
                start.ArgumentList.Add(Path.GetFullPath(script));
                // Pass data through argv, never interpolate AppleScript or shell code.
                start.ArgumentList.Add(tile.ItermId.Split(':').Last());
                start.ArgumentList.Add(tile.Tty);
                using var process = Process.Start(start) ?? throw new IOException("Cannot start osascript");
                if (!process.WaitForExit(5000)) { process.Kill(); throw new IOException("iTerm focus timed out"); }
                if (process.ExitCode != 0) throw new IOException("iTerm target missing or macOS Automation permission denied.");
            }
            catch (Exception ex) { error = ex.Message; }
            _focusError = error;
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(StatePath)!);
                File.WriteAllText(Path.Combine(Path.GetDirectoryName(StatePath)!, "focus-status.txt"),
                    DateTimeOffset.UtcNow.ToString("O") + " " + (error.Length == 0 ? "Focused iTerm" : error));
            }
            catch (IOException) { }
            Notify();
        });
    }
    public static string FocusStatus => _focusError.Length > 0 ? "NO FOCUS" : "";
}

public sealed class AgentSlotCommand : PluginDynamicCommand
{
    public AgentSlotCommand()
    {
        for (int i = 0; i < 9; i++) AddParameter(i.ToString(), $"Agent slot {i + 1}", "Agents");
    }
    protected override bool OnLoad() { Dashboard.Changed += Redraw; return true; }
    protected override bool OnUnload() { Dashboard.Changed -= Redraw; return true; }
    private void Redraw() { for (int i = 0; i < 9; i++) ActionImageChanged(i.ToString()); }
    protected override void RunCommand(string actionParameter)
    {
        if (int.TryParse(actionParameter, out int slot) && slot is >= 0 and < 9) Dashboard.Focus(Dashboard.Get(slot));
    }
    protected override string GetCommandDisplayName(string actionParameter, PluginImageSize imageSize)
        => TileFor(actionParameter)?.Text ?? $"{Dashboard.PageText}\nEmpty";
    private static Tile? TileFor(string parameter) => int.TryParse(parameter, out int i) && i is >= 0 and < 9 ? Dashboard.Get(i) : null;
    protected override BitmapImage GetCommandImage(string actionParameter, PluginImageSize imageSize)
    {
        var tile = TileFor(actionParameter);
        using var b = new BitmapBuilder(imageSize);
        var status = tile?.Status ?? "";
        b.Clear(status switch
        {
            "APPROVAL?" => new BitmapColor(110, 65, 0),
            "WORKING" or "TOOL" or "COMPACT" => new BitmapColor(0, 55, 95),
            "TURN STOP" or "STOPPED" => new BitmapColor(0, 70, 40),
            "EXIT ERROR" or "READ ERROR" => new BitmapColor(105, 20, 30),
            _ => new BitmapColor(32, 38, 48)
        });
        b.DrawText(tile?.Text ?? $"Page {Dashboard.PageText}\nEmpty");
        return b.ToImage();
    }
}

public sealed class NextPageCommand : PluginDynamicCommand
{
    public NextPageCommand() : base("Next agent page", "Show the next nine rows", "Agents") { }
    protected override bool OnLoad() { Dashboard.Changed += Redraw; return true; }
    protected override bool OnUnload() { Dashboard.Changed -= Redraw; return true; }
    private void Redraw() => ActionImageChanged();
    protected override void RunCommand(string actionParameter) => Dashboard.Move(1);
    protected override string GetCommandDisplayName(string p, PluginImageSize s)
        => $"Page {Dashboard.PageText}\n{Dashboard.FocusStatus}";
}

public sealed class AgentPageAdjustment : PluginDynamicAdjustment
{
    public AgentPageAdjustment() : base("Agent pages", "Rotate to browse nine agents per page", "Agents", false) { }
    protected override bool OnLoad() { Dashboard.Changed += Redraw; return true; }
    protected override bool OnUnload() { Dashboard.Changed -= Redraw; return true; }
    private void Redraw() => AdjustmentValueChanged();
    protected override void ApplyAdjustment(string actionParameter, int diff) => Dashboard.Move(diff);
    protected override string GetAdjustmentValue(string actionParameter) => Dashboard.PageText;
}
