using System.Diagnostics;
using System.Text.Json;

namespace Loupedeck.CodexMxPlugin;

internal static class PetDisplay
{
    private static readonly object Gate = new();
    private static readonly Stopwatch Clock = Stopwatch.StartNew();
    private static DisplayOptions _options = new();
    private static PetManifest? _manifest;
    private static Dictionary<string, BitmapImage> _images = new();
    private static string _fingerprint = "";
    private static string _renderStatus = "";
    private static bool _retry;

    public static bool Refresh(string root)
    {
        string fingerprint;
        DisplayOptions options;
        PetManifest? manifest = null;
        var images = new Dictionary<string, BitmapImage>();
        string error = "";
        try
        {
            string path = Path.Combine(root, "display.json");
            var info = new FileInfo(path);
            if (info.Exists && info.Length > 8192) throw new InvalidDataException("display.json exceeds 8 KiB");
            var raw = info.Exists ? File.ReadAllText(path) : "{\"schema_version\":1,\"mode\":\"text\"}";
            lock (Gate) if (raw == _fingerprint && !_retry) return false;
            options = DisplayOptions.Parse(raw);
            fingerprint = raw;
            if (options.Mode == "pet")
            {
                string folder = Path.Combine(root, "pets", options.Pet.Replace('/', Path.DirectorySeparatorChar));
                string manifestPath = Path.Combine(folder, "manifest.json");
                if (new FileInfo(manifestPath).Length > 65536) throw new InvalidDataException("Oversize pet manifest");
                manifest = PetManifest.Parse(File.ReadAllText(manifestPath));
                foreach (var name in manifest.Animations.Values.SelectMany(v => v).Distinct())
                    images[name] = BitmapImage.FromArray(DisplayPlan.ReadPng(Path.Combine(folder, name), manifest.FrameWidth, manifest.FrameHeight));
            }
        }
        catch (Exception ex)
        {
            options = new();
            manifest = null;
            images.Clear();
            fingerprint = "error:" + ex.GetType().Name + ":" + ex.Message;
            error = ex.Message;
        }
        bool changed;
        lock (Gate)
        {
            changed = fingerprint != _fingerprint;
            _fingerprint = fingerprint;
            _options = options;
            _manifest = manifest;
            _images = images;
            _retry = error.Length > 0;
        }
        if (changed)
            try
            {
                Directory.CreateDirectory(root);
                if (!OperatingSystem.IsWindows())
                    File.SetUnixFileMode(root, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
                File.WriteAllText(Path.Combine(root, "display-status.txt"), error.Length == 0 ?
                    $"{DateTimeOffset.UtcNow:O} mode={options.Mode}; fps={options.Fps}; animate={options.Animate}" :
                    $"{DateTimeOffset.UtcNow:O} Text fallback: {error}");
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException) { Trace.WriteLine(ex.Message); }
        return changed;
    }

    public static void Clear()
    {
        lock (Gate) { _manifest = null; _images.Clear(); _fingerprint = ""; _renderStatus = ""; _retry = false; _options = new(); }
    }

    public static void ReportRenderError(Exception error)
    {
        var message = $"Text fallback: {error.GetType().Name}: {error.Message}";
        ReportRenderStatus(message, message);
    }

    private static void ReportRenderStatus(string key, string message)
    {
        lock (Gate)
        {
            if (_renderStatus == key) return;
            _renderStatus = key;
        }
        try
        {
            var path = Path.Combine(Path.GetDirectoryName(Dashboard.StatePath)!, "render-status.txt");
            File.WriteAllText(path, $"{DateTimeOffset.UtcNow:O} {message}");
            if (!OperatingSystem.IsWindows())
                File.SetUnixFileMode(path, UnixFileMode.UserRead | UnixFileMode.UserWrite);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException) { Trace.WriteLine(ex.Message); }
    }

    private static void DrawLabel(BitmapBuilder target, string text, int top, int height, BitmapColor background)
    {
        // Newer hosts add a parameter to the positioned DrawText overload.
        // A separate canvas lets us use the binary-compatible simple overload.
        using var label = new BitmapBuilder(target.Width, height);
        label.Clear(background);
        label.DrawText(text);
        target.DrawImage(label.ToImage(), 0, top);
    }

    private static string? FileFor(Tile tile)
    {
        if (_options.Mode != "pet" || _manifest is null || tile.Host == "bridge") return null;
        var (state, moves) = DisplayPlan.Animation(tile.Status);
        var frames = _manifest.Animations[state];
        return frames[DisplayPlan.Frame(frames.Length, _options.Fps, _options.Animate && moves, Clock.Elapsed.TotalSeconds)];
    }

    public static string? FrameKey(Tile? tile)
    {
        if (tile is null) return null;
        lock (Gate)
        {
            var file = FileFor(tile);
            return file is null ? null : $"{tile.Key}/{tile.Status}/{_options.Pet}/{file}";
        }
    }

    public static BitmapColor Background(string status) => status switch
    {
        "APPROVAL?" => new BitmapColor(110, 65, 0),
        "WORKING" or "TOOL" or "COMPACT" => new BitmapColor(0, 55, 95),
        "TURN STOP" or "STOPPED" => new BitmapColor(0, 70, 40),
        "EXIT ERROR" or "TURN ERROR" or "READ ERROR" => new BitmapColor(105, 20, 30),
        _ => new BitmapColor(32, 38, 48)
    };

    public static BitmapImage? Render(Tile? tile, PluginImageSize size)
    {
        if (tile is null) return null;
        lock (Gate)
        {
            var file = FileFor(tile);
            if (file is null || _manifest is null || !_images.TryGetValue(file, out var frame)) return null;
            using var b = new BitmapBuilder(size);
            int header = Math.Max(20, b.Height/4), footer = Math.Max(16, b.Height/6);
            double scale = Math.Min((b.Width-8.0)/_manifest.FrameWidth, (b.Height-header-footer-4.0)/_manifest.FrameHeight);
            int w = Math.Max(1, (int)(_manifest.FrameWidth*scale)), h = Math.Max(1, (int)(_manifest.FrameHeight*scale));
            var background = Background(tile.Status);
            b.Clear(background);
            DrawLabel(b, $"{tile.Header}\n{tile.Name}", 0, header, background);
            b.DrawImage(frame, (b.Width-w)/2, header+(b.Height-header-footer-h)/2, w, h);
            DrawLabel(b, tile.Status, b.Height-footer, footer, background);
            var image = b.ToImage();
            ReportRenderStatus($"pet:{_options.Pet}", $"Rendered pet {_options.Pet}; image={b.Width}x{b.Height}");
            return image;
        }
    }
}
