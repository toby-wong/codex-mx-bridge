using System.Reflection;

namespace Loupedeck.CodexMxPlugin;

internal static class FocusScript
{
    public static string Read(Assembly assembly)
    {
        // Logi can load plugin bytes directly, leaving Assembly.Location empty.
        using var stream = assembly.GetManifestResourceStream("CodexMxPlugin.focus.applescript") ??
            throw new InvalidOperationException("Embedded focus script is missing; reinstall the bridge plugin.");
        using var reader = new StreamReader(stream);
        return reader.ReadToEnd();
    }
}
