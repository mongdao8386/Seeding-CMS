// Seeding.exe - mot nut bam de mo he thong.
//
// Ghim file nay vao taskbar (chuot phai -> Ghim vao thanh tac vu). Bam:
//   - dashboard dang chay (cong 3000 tra loi)  -> chi mo trinh duyet.
//   - chua chay                                 -> chay Start.cmd (bat Docker, API, signer,
//                                                  worker, dashboard; tu mo trinh duyet khi xong).
//   Seeding.exe --stop                          -> chay Stop.cmd.
//
// Khong co logic gi khac o day: moi thu ve bat/tat nam trong scripts/launch.ps1. File nay chi
// la cai vo co icon de Windows cho ghim. Build: scripts/build_launcher.ps1 (dung csc.exe cua
// .NET Framework co san trong Windows, khong cai them gi).

using System;
using System.Diagnostics;
using System.IO;
using System.Net.Sockets;
using System.Windows.Forms;

internal static class Program
{
    private const int WebPort = 3000;
    private const string DashboardUrl = "http://127.0.0.1:3000";

    [STAThread]
    private static int Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        bool stop = args.Length > 0 && args[0] == "--stop";
        string script = Path.Combine(root, stop ? "Stop.cmd" : "Start.cmd");

        if (!File.Exists(script))
        {
            MessageBox.Show(
                "Không thấy " + Path.GetFileName(script) + " cạnh Seeding.exe.\n\n" +
                "Seeding.exe phải nằm trong thư mục gốc của dự án (cùng chỗ với Start.cmd).",
                "Seeding", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 2;
        }

        if (!stop && PortOpen(WebPort))
        {
            OpenBrowser();
            return 0;
        }

        var psi = new ProcessStartInfo
        {
            FileName = "cmd.exe",
            Arguments = "/c \"" + script + "\"",
            WorkingDirectory = root,
            UseShellExecute = true,
        };
        try
        {
            Process.Start(psi);
        }
        catch (Exception exc)
        {
            MessageBox.Show("Không chạy được " + Path.GetFileName(script) + ":\n" + exc.Message,
                "Seeding", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        return 0;
    }

    private static bool PortOpen(int port)
    {
        try
        {
            using (var client = new TcpClient())
            {
                var task = client.ConnectAsync("127.0.0.1", port);
                return task.Wait(700) && client.Connected;
            }
        }
        catch
        {
            return false;
        }
    }

    private static void OpenBrowser()
    {
        try
        {
            Process.Start(new ProcessStartInfo { FileName = DashboardUrl, UseShellExecute = true });
        }
        catch (Exception exc)
        {
            MessageBox.Show("Không mở được trình duyệt: " + exc.Message + "\n\nMở tay: " + DashboardUrl,
                "Seeding", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }
}
