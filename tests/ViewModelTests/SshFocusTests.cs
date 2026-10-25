using System.Diagnostics;
using System.Text.Json;
using Loupedeck.CodexMxPlugin;

internal static class SshFocusTests
{
    public static async Task<int> Run()
    {
        if (OperatingSystem.IsWindows()) return 0;
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
            throw new Exception("Expected SSH rejection: " + message);
        }
        string folder = Path.Combine(Path.GetTempPath(), "mx-ssh-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(folder);
        string ssh = Path.Combine(folder, "ssh"), herdr = Path.Combine(folder, "herdr with ' quote");
        string arguments = Path.Combine(folder, "arguments"), marker = Path.Combine(folder, "injected");
        void Script(string path, string body)
        {
            File.WriteAllText(path, "#!/bin/sh\n" + body + "\n");
            File.SetUnixFileMode(path, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
        }
        var binding = new HerdrRemoteBinding { Source = "source", SshTarget = "user@workbox",
            HerdrPath = herdr, RemoteSession = "work", ItermId = "12345678-1234-1234-1234-123456789abc" };
        string response = "{\"id\":\"cli:agent:get\",\"result\":{\"type\":\"agent_info\"}}";
        async Task<JsonElement> Request(string method = "agent.get", string target = "w1:p2")
        {
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(3));
            return await HerdrSsh.RequestAsync(binding, method, new { target }, deadline.Token, ssh);
        }
        try
        {
            // Emulate OpenSSH's last-argument remote shell boundary locally.
            Script(ssh, "for argument do :; done\nexec /bin/sh -c \"$argument\"");
            Script(herdr, "if [ \"$#\" -ne 5 ]; then exit 2; fi\n" +
                $"printf '%s\\n' \"$@\" > '{arguments}'\nprintf '%s\\n' '{response}'");
            string target = $"w1:p2'; touch '{marker}'; echo '";
            var result = await Request(target: target);
            Check(HerdrFocus.Text(result, "type") == "agent_info", "SSH CLI envelope is decoded");
            Check(File.ReadAllLines(arguments).SequenceEqual(new[] { "--session", "work", "agent", "get", target }),
                  "quoted arguments preserve Herdr 0.9.5's single-target syntax without a separator");
            Check(!File.Exists(marker), "a server-supplied pane string cannot execute a shell command");
            var start = HerdrSsh.StartInfo(binding, "agent.list", new { });
            foreach (string flag in new[] { "-n", "-T", "BatchMode=yes", "StrictHostKeyChecking=yes",
                "ClearAllForwardings=yes", "ForwardAgent=no", "ForwardX11=no", "RemoteCommand=none" })
                Check(start.ArgumentList.Contains(flag), "SSH focus keeps noninteractive trust and forwarding limits");
            Check(start.FileName == "/usr/bin/ssh" && !start.UseShellExecute,
                  "the plugin launches the system SSH executable without a local shell");
            await Reject(() => Request("pane.run"), "Unsupported Herdr focus operation");
            await Reject(() => Request(target: "bad\npane"), "Invalid Herdr pane target");
            await Reject(() => Request(target: "--help"), "Invalid Herdr pane target");

            string muxPath = Path.Combine(folder, "mux-path"), closed = Path.Combine(folder, "closed");
            Script(ssh, $"if [ \"$1\" = '-O' ]; then touch '{closed}'; exit 0; fi\n" +
                $"for argument do case \"$argument\" in ControlPath=*) printf '%s' \"${{argument#ControlPath=}}\" > '{muxPath}';; esac; done\n" +
                "printf '%s\\n' '{\"id\":\"cli:agent:list\",\"result\":{\"type\":\"agent_list\",\"agents\":[]}}'");
            string controlDirectory;
            await using (var transport = new HerdrTransport(ssh))
            {
                var endpoint = new HerdrEndpoint(binding.ItermId, Remote: binding);
                await transport.RequestAsync(endpoint, "agent.list", new { }, CancellationToken.None);
                string firstPath = File.ReadAllText(muxPath);
                controlDirectory = Path.GetDirectoryName(firstPath)!;
                Check((File.GetUnixFileMode(controlDirectory) & (UnixFileMode)0x3f) == 0,
                      "each focus action uses a private SSH control directory");
                Check(firstPath.Replace("%C", new string('a', 40)).Length + 17 < 104,
                      "expanded SSH socket and temporary suffix fit the macOS socket path limit");
                await transport.RequestAsync(endpoint, "agent.list", new { }, CancellationToken.None);
                Check(File.ReadAllText(muxPath) == firstPath, "lookups and focus reuse one action's SSH connection");
            }
            Check(File.Exists(closed) && !Directory.Exists(controlDirectory),
                  "disposal closes only the owned SSH master and removes its temporary directory");

            Script(ssh, "printf '%s\\n' '{\"id\":\"wrong\",\"result\":{}}'");
            await Reject(() => Request(), "response ID");
            Script(ssh, "printf '%s\\n' '{\"id\":\"cli:agent:get\",\"error\":{\"message\":\"private\"}}'");
            await Reject(() => Request(), "rejected agent.get");
            Script(ssh, "printf '%s\\n' '{\"id\":\"cli:agent:get\",\"result\":null}'");
            await Reject(() => Request(), "Missing remote Herdr response");
            Script(ssh, "printf '%s\\n' '{\"id\":\"cli:agent:get\",\"result\":{}}'\nexit 255");
            await Reject(() => Request(), "SSH exit 255");
            Script(ssh, "printf '%s\\n' 'not json'");
            bool badJson = false;
            try { await Request(); }
            catch (JsonException) { badJson = true; }
            Check(badJson, "Non-JSON SSH output is rejected");

            Script(ssh, "head -c 1048577 /dev/zero\nsleep 30");
            await Reject(() => Request(), "response exceeds");
            Script(ssh, "head -c 16385 /dev/zero >&2\nsleep 30");
            await Reject(() => Request(), "SSH error exceeds");
            string pidFile = Path.Combine(folder, "pid");
            Script(ssh, $"echo $$ > '{pidFile}'\nexec sleep 30");
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(3));
            var waiting = HerdrSsh.RequestAsync(binding, "agent.list", new { }, deadline.Token, ssh);
            while (!File.Exists(pidFile)) await Task.Delay(10, deadline.Token);
            deadline.Cancel();
            bool interrupted = false;
            try { await waiting; }
            catch (OperationCanceledException) { interrupted = true; }
            Check(interrupted, "Unresponsive SSH respects cancellation");

            int pid = int.Parse(File.ReadAllText(pidFile));
            try
            {
                using var process = Process.GetProcessById(pid);
                using var exitDeadline = new CancellationTokenSource(TimeSpan.FromSeconds(2));
                await process.WaitForExitAsync(exitDeadline.Token);
            }
            catch (ArgumentException) { } // Already reaped.
            count++;
            File.Delete(pidFile);
            using var cancelled = new CancellationTokenSource();
            cancelled.Cancel();
            bool expired = false;
            try { await HerdrSsh.RequestAsync(binding, "agent.list", new { }, cancelled.Token, ssh); }
            catch (OperationCanceledException) { expired = true; }
            Check(expired && !File.Exists(pidFile), "an expired focus request never starts SSH");
            return count;
        }
        finally { Directory.Delete(folder, recursive: true); }
    }
}
