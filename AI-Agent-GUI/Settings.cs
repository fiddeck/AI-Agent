using System;
using System.IO;
using System.Text.Json;

namespace AIAgentGUI;

/// <summary>
/// GUI/网页版共享的自定义设置, 持久化到项目根目录 settings.json。
/// 网页版 (webui.py) 启动时也会读取同一文件, 实现两端配置互通。
/// </summary>
public sealed class GuiSettings
{
    public string Model { get; set; } = "deepseek-v4-flash";
    public string BaseUrl { get; set; } = "https://api.deepseek.com";
    public string ApiKey { get; set; } = "";          // 留空则使用系统环境变量
    public int Port { get; set; } = 8000;
    public double FontSize { get; set; } = 14;
    public string Accent { get; set; } = "#4D9FFF";      // 主题色
    public string Background { get; set; } = "#0C1117";  // 背景色 (默认深色, 与桌面版深色外壳一致)

    private const string FileName = "settings.json";

    public static GuiSettings Load(string rootDir)
    {
        try
        {
            var path = Path.Combine(rootDir, FileName);
            if (!File.Exists(path))
            {
                // 兼容旧版本文件名
                var old = Path.Combine(rootDir, "gui_settings.json");
                if (File.Exists(old)) path = old;
                else return new GuiSettings();
            }
            var json = File.ReadAllText(path);
            return JsonSerializer.Deserialize<GuiSettings>(json) ?? new GuiSettings();
        }
        catch
        {
            return new GuiSettings();
        }
    }

    public void Save(string rootDir)
    {
        try
        {
            var path = Path.Combine(rootDir, FileName);
            File.WriteAllText(path,
                JsonSerializer.Serialize(this, new JsonSerializerOptions { WriteIndented = true }));
        }
        catch
        {
            // 保存失败不阻塞使用
        }
    }

    /// <summary>后端相关配置是否变化 (需要重启后端才生效)。主题色/字号即时生效, 不算。</summary>
    public bool BackendChanged(GuiSettings other) =>
        Model != other.Model || BaseUrl != other.BaseUrl ||
        ApiKey != other.ApiKey || Port != other.Port;
}
