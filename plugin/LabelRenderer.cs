namespace Loupedeck.CodexMxPlugin;

internal static class LabelRenderer
{
    private sealed record Key(string Text, int Width, int Height, string Status);
    private static readonly object Gate = new();
    private static readonly Dictionary<Key, BitmapImage> Images = new();

    public static void Clear()
    {
        lock (Gate) Images.Clear();
    }

    public static void Draw(BitmapBuilder target, string text, int top, int height, string status)
    {
        if (height <= 0 || text.Length == 0) return;
        lock (Gate)
        {
            var key = new Key(text, target.Width, height, status);
            if (!Images.TryGetValue(key, out var image))
            {
                image = Render(text, target.Width, height, status);
                if (Images.Count >= 128) Images.Clear();
                Images[key] = image;
            }
            target.DrawImage(image, 0, top);
        }
    }

    private static BitmapImage Render(string text, int width, int height, string status)
    {
        var measured = new Dictionary<(string, int), int>();
        int Measure(string value, int size)
        {
            var key = (value, size);
            if (!measured.TryGetValue(key, out int result))
                measured[key] = result = MeasureInk(value, size);
            return result;
        }
        var layout = LabelLayout.Fit(text, Math.Max(1, width - 8), Math.Max(1, height - 2), Measure);
        var background = PetDisplay.Background(status);
        using var label = new BitmapBuilder(width, height);
        label.Clear(background);
        int y = Math.Max(0, (height - layout.Lines.Length * layout.LineHeight) / 2);
        foreach (string line in layout.Lines)
        {
            // Single-line canvases avoid SDK paragraph spacing and the positioned
            // DrawText overload whose signature changed in newer Logi hosts.
            using var row = new BitmapBuilder(width, layout.LineHeight);
            row.Clear(background);
            row.DrawText(line, fontSize: layout.FontSize, lineHeight: layout.LineHeight, spaceHeight: 0);
            label.DrawImage(row.ToImage(), 0, y);
            y += layout.LineHeight;
        }
        return label.ToImage();
    }

    private static int MeasureInk(string text, int size)
    {
        // Measure the SDK's actual font without binding to its SkiaSharp version.
        // This runs only when a label changes; pet animation reuses cached images.
        if (text.Length == 0) return 0;
        int width = Math.Max(64, (text.Length + 2) * size * 2);
        int height = size * 3 + 8;
        using var sample = new BitmapBuilder(width, height);
        sample.Clear(new BitmapColor(0, 0, 0));
        sample.DrawText(text, new BitmapColor(255, 255, 255), fontSize: size, lineHeight: size + 2, spaceHeight: 0);
        byte[] pixels = sample.ToArray(BitmapImageFormat.Rgb888);
        if (pixels.Length != width * height * 3)
            throw new InvalidDataException("Unexpected SDK text measurement bitmap");
        int left = width, right = -1;
        for (int y = 0; y < height; y++)
            for (int x = 0; x < width; x++)
            {
                int p = (y * width + x) * 3;
                if (pixels[p] == 0 && pixels[p + 1] == 0 && pixels[p + 2] == 0) continue;
                left = Math.Min(left, x);
                right = Math.Max(right, x);
            }
        // Include centering/side-bearing slack as well as the visible glyphs.
        return right < left ? 0 : 2 * Math.Max(width / 2 - left, right + 1 - width / 2) + 2;
    }
}
