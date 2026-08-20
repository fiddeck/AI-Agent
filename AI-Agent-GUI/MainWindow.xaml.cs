using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Windows.System;
using Microsoft.UI.Text;
using DispatcherQueue = Microsoft.UI.Dispatching.DispatcherQueue;

namespace AIAgentGUI;

public sealed partial class MainWindow : Window
{
    private readonly ChatService _chat = new();
    private readonly DispatcherQueue _ui = DispatcherQueue.GetForCurrentThread();

    private static readonly int DefaultPort =
        int.TryParse(Environment.GetEnvironmentVariable("WEBUI_PORT"), out var p) ? p : 8000;

    private int _port = DefaultPort;   // 实际使用端口 (被占用时自动顺延)

    private GuiSettings _settings = new();   // 自定义设置 (gui_settings.json)
    private string? _projectRoot;
    private double _fontSize = 14;           // 消息字号

    private static readonly HttpClient Http = new() { Timeout = TimeSpan.FromSeconds(1) };

    private string? _currentSid;
    private List<SessionInfo> _sessions = new();
    private bool _suppressSelect;
    private bool _streaming;
    private string _acc = "";

    // 当前助手气泡的构建句柄
    private StackPanel? _assistantContent;
    private StackPanel? _assistantTools;
    private TextBlock? _lastResultText;

    private Process? _serverProcess;   // 由本窗口拉起的后端进程 (退出时清理)

    public MainWindow()
    {
        InitializeComponent();
        try
        {
            AppWindow.Resize(new Windows.Graphics.SizeInt32(1100, 720));
        }
        catch { /* 部分环境不支持, 忽略 */ }
        Closed += (_, _) =>
        {
            try
            {
                if (_serverProcess != null && !_serverProcess.HasExited)
                    _serverProcess.Kill();
            }
            catch { /* 忽略清理异常 */ }
        };
        _ = InitAsync();
    }

    // ==================== 初始化 ====================

    private async Task InitAsync()
    {
        _chat.SessionChanged += sid => Dispatch(() =>
        {
            _currentSid = sid;
            ClearMessages();
            SetStatus("已连接", false);
        });
        _chat.SessionsUpdated += list => Dispatch(() => RefreshSessions(list));
        _chat.HistoryReceived += (sid, msgs) => Dispatch(() =>
        {
            _currentSid = sid;
            RenderHistory(msgs);
        });
        _chat.TokenReceived += c => Dispatch(() => OnToken(c));
        _chat.ToolCallReceived += (n, a) => Dispatch(() => AddToolCard(n, a));
        _chat.ToolResultReceived += (_, c) => Dispatch(() => SetToolResult(c));
        _chat.TurnDone += () => Dispatch(() => OnDone());
        _chat.ErrorReceived += msg => Dispatch(() => OnError(msg));
        _chat.Disconnected += () => Dispatch(() => SetStatus("连接断开, 请重启应用", false));

        // 加载自定义设置 (模型/地址/密钥/端口/字号/主题色)
        _projectRoot = FindProjectRoot();
        if (_projectRoot != null)
        {
            _settings = GuiSettings.Load(_projectRoot);
            _port = _settings.Port;
            _fontSize = _settings.FontSize;
            UiColors.Apply(_settings.Accent, _settings.Background);
            ApplyDisplaySettings();
        }

        SetStatus("正在启动后端服务…", true);
        var (ok, reason) = await EnsureServerAsync();
        if (!ok)
        {
            Dispatch(() => ShowFatal(
                "无法启动后端服务:\n" + reason + "\n\n排查步骤:\n" +
                "1) 确认环境变量 OPENAI_API_KEY 已设置 (建议用 setx 设为系统变量后重启应用)\n" +
                "2) 确认依赖已装齐: .venv\\Scripts\\python -c \"import fastapi,uvicorn,websockets\"\n" +
                "3) 双击项目根目录 webui.bat 前台运行, 直接看后端真实报错"));
            return;
        }
        SetStatus("正在连接…", true);
        try
        {
            await _chat.ConnectAsync($"ws://127.0.0.1:{_port}/ws");
        }
        catch (Exception ex)
        {
            Dispatch(() => ShowFatal(
                "无法连接后端 WebSocket:\n" + ex.Message +
                "\n\n请确认后端已启动 (可先运行 webui.bat 验证后再启动本程序)"));
            return;
        }
        await _chat.SendNewChat();

        // 首次使用: 设置与环境变量都没有 API Key 时, 自动弹窗引导配置
        if (string.IsNullOrEmpty(_settings.ApiKey) &&
            string.IsNullOrEmpty(Environment.GetEnvironmentVariable("OPENAI_API_KEY")))
        {
            await Task.Delay(800);   // 等窗口完成激活
            Dispatch(() => OpenSettingsDialog(true));
        }
    }

    // ==================== 后端服务引导 ====================

    private static async Task<bool> IsServerUpAsync(int port)
    {
        try
        {
            using var r = await Http.GetAsync($"http://127.0.0.1:{port}/");
            return r.IsSuccessStatusCode;
        }
        catch { return false; }
    }

    /// <summary>在默认端口附近找已在运行的本项目后端 (通过页面标题识别), 找到则复用。</summary>
    private static async Task<int> FindExistingServerAsync(int start)
    {
        for (int port = start; port < start + 10; port++)
        {
            try
            {
                using var cts = new CancellationTokenSource(TimeSpan.FromMilliseconds(400));
                using var r = await Http.GetAsync($"http://127.0.0.1:{port}/", cts.Token);
                if (r.IsSuccessStatusCode)
                {
                    var body = await r.Content.ReadAsStringAsync();
                    if (body.Contains("AI Agent")) return port;
                }
            }
            catch { /* 无服务或超时, 试下一个 */ }
        }
        return 0;
    }

    private static async Task<int> FindFreePortAsync(int start)
    {
        for (int port = start; port < start + 60; port++)
        {
            try
            {
                var listener = new System.Net.Sockets.TcpListener(System.Net.IPAddress.Loopback, port);
                listener.Start();
                listener.Stop();
                return port;
            }
            catch { /* 端口被占用或保留, 试下一个 */ }
        }
        return 0;
    }

    private async Task<(bool Ok, string Reason)> EnsureServerAsync()
    {
        // 1) 复用已在运行的本项目后端 (webui.bat 拉起的实例也能被找到)
        var existing = await FindExistingServerAsync(_port);
        if (existing > 0)
        {
            _port = existing;
            return (true, "");
        }

        // 2) 默认端口常被系统保留 (Hyper-V/WSL 排除端口段), 自动换一个空闲端口
        var freePort = await FindFreePortAsync(_port + 1);
        if (freePort == 0) return (false, "未找到可用端口 (已尝试 60 个)。");
        _port = freePort;

        var root = _projectRoot ??= FindProjectRoot();
        if (root == null) return (false, "找不到项目根目录 (向上查找 10 层未发现 webui.py)。");
        var python = Path.Combine(root, ".venv", "Scripts", "python.exe");
        var script = Path.Combine(root, "webui.py");
        if (!File.Exists(python)) return (false, $"缺少 {python}");
        if (!File.Exists(script)) return (false, $"缺少 {script}");

        var logPath = Path.Combine(root, "webui.log");
        Process? proc = null;
        try
        {
            var psi = new ProcessStartInfo(python, $"\"{script}\"")
            {
                WorkingDirectory = root,
                CreateNoWindow = true,
                UseShellExecute = false,
                WindowStyle = ProcessWindowStyle.Hidden,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            };
            psi.Environment["WEBUI_PORT"] = _port.ToString();
            psi.Environment["OPENAI_MODEL"] = _settings.Model;
            psi.Environment["OPENAI_BASE_URL"] = _settings.BaseUrl;
            if (!string.IsNullOrEmpty(_settings.ApiKey))
                psi.Environment["OPENAI_API_KEY"] = _settings.ApiKey;
            proc = Process.Start(psi);
            if (proc == null) return (false, "后端进程启动失败。");
            _serverProcess = proc;

            // 后台把 stdout/stderr 排空写入 webui.log, 便于诊断
            var captured = proc;
            _ = Task.Run(async () =>
            {
                try
                {
                    using var sw = new StreamWriter(logPath, false) { AutoFlush = true };
                    await sw.WriteLineAsync($"[{DateTime.Now:HH:mm:ss}] === AI-Agent webui 日志 ===");
                    var t1 = Task.Run(async () =>
                    {
                        var s = await captured.StandardOutput.ReadToEndAsync();
                        await sw.WriteLineAsync("[stdout]\n" + s);
                    });
                    var t2 = Task.Run(async () =>
                    {
                        var s = await captured.StandardError.ReadToEndAsync();
                        await sw.WriteLineAsync("[stderr]\n" + s);
                    });
                    await Task.WhenAll(t1, t2);
                }
                catch { /* 日志写入失败不影响主流程 */ }
            });
        }
        catch (Exception ex)
        {
            return (false, $"启动异常: {ex.Message}");
        }

        // 轮询等待服务就绪 (最多 30 秒), 提前退出则直接报日志
        for (int i = 0; i < 60; i++)
        {
            await Task.Delay(500);
            if (await IsServerUpAsync(_port)) return (true, "");
            if (proc.HasExited)
                return (false, $"后端进程提前退出 (退出码 {proc.ExitCode})。\n日志:\n" + ReadLogTail(logPath));
        }
        return (false, $"后端服务 30 秒内未就绪。\n日志:\n" + ReadLogTail(logPath));
    }

    private static string ReadLogTail(string logPath, int maxChars = 2000)
    {
        try
        {
            if (!File.Exists(logPath)) return "(无日志文件)";
            var text = File.ReadAllText(logPath);
            if (text.Length <= maxChars) return text;
            return "…(日志过长已截断)…\n" + text.Substring(text.Length - maxChars);
        }
        catch (Exception ex)
        {
            return $"(读取日志失败: {ex.Message})";
        }
    }

    private static string? FindProjectRoot()
    {
        var env = Environment.GetEnvironmentVariable("AI_AGENT_ROOT");
        if (!string.IsNullOrEmpty(env) && File.Exists(Path.Combine(env, "webui.py"))) return env;

        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        for (int i = 0; i < 10 && dir != null; i++, dir = dir.Parent)
        {
            if (File.Exists(Path.Combine(dir.FullName, "webui.py"))) return dir.FullName;
        }
        return null;
    }

    // ==================== UI 工具 ====================

    private void Dispatch(Action action) => _ui.TryEnqueue(() =>
    {
        try { action(); }
        catch (Exception ex) { ShowInlineError("界面异常: " + ex.Message); }
    });

    private void ShowInlineError(string message)
    {
        MessagePanel.Children.Add(new TextBlock
        {
            Text = "⚠️ " + message,
            FontSize = 12,
            Foreground = UiColors.Brush(UiColors.Danger),
            TextWrapping = TextWrapping.Wrap,
        });
    }

    private void SetStatus(string text, bool thinking)
    {
        StatusText.Text = text;
        StatusDot.Fill = new SolidColorBrush(thinking ? UiColors.Accent : UiColors.Green);
    }

    private void ScrollToBottom()
    {
        try
        {
            MessageScroll.UpdateLayout();
            // WinUI 3 的 ChangeView 拒绝无穷值, 必须用有限的可滚动高度
            MessageScroll.ChangeView(null, MessageScroll.ScrollableHeight, null, true);
        }
        catch { /* 布局尚未就绪时忽略 */ }
    }

    private void ClearMessages()
    {
        MessagePanel.Children.Clear();
        _acc = "";
        _assistantContent = null;
        _assistantTools = null;
        _lastResultText = null;
        _streaming = false;
    }

    private void RefreshSessions(List<SessionInfo> list)
    {
        _sessions = list;
        _suppressSelect = true;
        SessionList.Items.Clear();
        ListViewItem? selected = null;
        foreach (var s in _sessions)
        {
            var item = new ListViewItem
            {
                Content = string.IsNullOrEmpty(s.Title) ? "新对话" : s.Title,
                Tag = s.Sid,
                FontSize = 13,
            };
            SessionList.Items.Add(item);
            if (s.Sid == _currentSid) selected = item;
        }
        if (selected != null) SessionList.SelectedItem = selected;
        _suppressSelect = false;
    }

    // ==================== 消息渲染 ====================

    private void AddUserMessage(string text)
    {
        var tb = new TextBlock
        {
            Text = text,
            TextWrapping = TextWrapping.Wrap,
            FontSize = _fontSize,
            Foreground = UiColors.Brush(UiColors.Text),
            IsTextSelectionEnabled = true,
        };
        var border = new Border
        {
            Background = UiColors.Brush(UiColors.UserBubble),
            CornerRadius = new CornerRadius(12, 4, 12, 12),
            Padding = new Thickness(12, 9, 12, 9),
            HorizontalAlignment = HorizontalAlignment.Right,
            MaxWidth = 560,
            Child = tb,
        };
        MessagePanel.Children.Add(border);
        ScrollToBottom();
    }

    private void BeginAssistantMessage()
    {
        var content = new StackPanel { Spacing = 6 };
        var tools = new StackPanel { Spacing = 6 };
        var panel = new StackPanel { Spacing = 8 };
        panel.Children.Add(content);
        panel.Children.Add(tools);

        var border = new Border
        {
            Background = UiColors.Brush(UiColors.Panel2),
            BorderBrush = UiColors.Brush(UiColors.Border),
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(4, 12, 12, 12),
            Padding = new Thickness(12, 10, 12, 10),
            HorizontalAlignment = HorizontalAlignment.Stretch,
            Child = panel,
        };
        MessagePanel.Children.Add(border);
        _assistantContent = content;
        _assistantTools = tools;
    }

    private void RenderAssistantText(string text, bool streaming)
    {
        if (_assistantContent == null) return;
        _assistantContent.Children.Clear();

        foreach (var block in MarkdownRenderer.SplitBlocks(text))
        {
            if (block.IsCode)
            {
                var codeText = new TextBlock
                {
                    Text = block.Text,
                    FontFamily = new FontFamily("Consolas"),
                    FontSize = 12.5,
                    Foreground = UiColors.Brush(UiColors.CodeText),
                    TextWrapping = TextWrapping.Wrap,
                    IsTextSelectionEnabled = true,
                };
                _assistantContent.Children.Add(new Border
                {
                    Background = UiColors.Brush(UiColors.CodeBg),
                    BorderBrush = UiColors.Brush(UiColors.Border),
                    BorderThickness = new Thickness(1),
                    CornerRadius = new CornerRadius(8),
                    Padding = new Thickness(12, 10, 12, 10),
                    Child = codeText,
                });
            }
            else
            {
                var tb = new TextBlock
                {
                    TextWrapping = TextWrapping.Wrap,
                    FontSize = _fontSize,
                    LineHeight = _fontSize + 8,
                    IsTextSelectionEnabled = true,
                };
                foreach (var inline in MarkdownRenderer.BuildInlines(block.Text))
                    tb.Inlines.Add(inline);
                _assistantContent.Children.Add(tb);
            }
        }

        if (streaming)
        {
            _assistantContent.Children.Add(new TextBlock
            {
                Text = "▍",
                FontSize = _fontSize,
                Foreground = UiColors.Brush(UiColors.Accent),
            });
        }
    }

    private static string PrettyArgs(string s)
    {
        try
        {
            using var doc = System.Text.Json.JsonDocument.Parse(s);
            return System.Text.Json.JsonSerializer.Serialize(
                doc.RootElement, new System.Text.Json.JsonSerializerOptions { WriteIndented = true });
        }
        catch { return s; }
    }

    private void AddToolCard(string name, string args)
    {
        if (_assistantTools == null) return;

        var header = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
        header.Children.Add(new TextBlock
        {
            Text = "🔧 " + name,
            FontSize = 12.5,
            FontWeight = FontWeights.SemiBold,
            Foreground = UiColors.Brush(UiColors.Accent),
        });
        var argsShort = args.Replace("\n", " ");
        if (argsShort.Length > 60) argsShort = argsShort.Substring(0, 60) + "…";
        header.Children.Add(new TextBlock
        {
            Text = argsShort,
            FontSize = 11.5,
            Foreground = UiColors.Brush(UiColors.Muted),
            TextTrimming = TextTrimming.CharacterEllipsis,
            MaxWidth = 420,
        });

        var body = new StackPanel { Spacing = 6 };
        body.Children.Add(new TextBlock
        {
            Text = PrettyArgs(args),
            FontFamily = new FontFamily("Consolas"),
            FontSize = 11.5,
            Foreground = UiColors.Brush(UiColors.Muted),
            TextWrapping = TextWrapping.Wrap,
        });
        _lastResultText = new TextBlock
        {
            Text = "(等待结果…)",
            FontFamily = new FontFamily("Consolas"),
            FontSize = 12,
            Foreground = UiColors.Brush(UiColors.CodeText),
            TextWrapping = TextWrapping.Wrap,
            IsTextSelectionEnabled = true,
        };
        body.Children.Add(_lastResultText);

        _assistantTools.Children.Add(new Expander
        {
            Header = header,
            Content = body,
            IsExpanded = false,
            Background = UiColors.Brush(UiColors.Panel2),
            BorderBrush = UiColors.Brush(UiColors.Border),
            BorderThickness = new Thickness(1),
        });
        ScrollToBottom();
    }

    private void SetToolResult(string content)
    {
        if (_lastResultText != null)
        {
            _lastResultText.Text = string.IsNullOrWhiteSpace(content) ? "(无输出)" : content;
            _lastResultText = null;
        }
        ScrollToBottom();
    }

    private void RenderHistory(List<HistoryMessage> msgs)
    {
        ClearMessages();
        foreach (var m in msgs)
        {
            if (m.Role == "user") AddUserMessage(m.Content);
            else
            {
                BeginAssistantMessage();
                RenderAssistantText(m.Content, false);
            }
        }
        ScrollToBottom();
    }

    // ==================== 事件: 后端 ====================

    private void OnToken(string content)
    {
        if (_assistantContent == null) BeginAssistantMessage();
        _acc += content;
        RenderAssistantText(_acc, true);
        ScrollToBottom();
    }

    private void OnDone()
    {
        if (_assistantContent != null) RenderAssistantText(_acc, false);
        _streaming = false;
        SetStatus("已连接", false);
        ScrollToBottom();
    }

    private void OnError(string message)
    {
        if (_assistantContent != null) RenderAssistantText(_acc, false);
        _streaming = false;
        var tb = new TextBlock
        {
            Text = "⚠️ " + message,
            FontSize = 13,
            Foreground = UiColors.Brush(UiColors.Danger),
            TextWrapping = TextWrapping.Wrap,
        };
        MessagePanel.Children.Add(new Border
        {
            Background = UiColors.Brush(UiColors.Panel2),
            BorderBrush = UiColors.Brush(UiColors.Danger),
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(8),
            Padding = new Thickness(12, 10, 12, 10),
            Child = tb,
        });
        SetStatus("出错了", false);
        ScrollToBottom();
    }

    private void ShowFatal(string message)
    {
        _streaming = false;
        var tb = new TextBlock
        {
            Text = message,
            FontSize = 13,
            Foreground = UiColors.Brush(UiColors.Danger),
            TextWrapping = TextWrapping.Wrap,
        };
        MessagePanel.Children.Add(tb);
        SetStatus("启动失败", false);
    }

    // ==================== 事件: UI ====================

    private void Send_Click(object sender, RoutedEventArgs e) => SendMessage();

    private void InputBox_KeyDown(object sender, KeyRoutedEventArgs e)
    {
        if (e.Key == VirtualKey.Enter && !(Microsoft.UI.Input.InputKeyboardSource
            .GetKeyStateForCurrentThread(VirtualKey.Shift).HasFlag(Windows.UI.Core.CoreVirtualKeyStates.Down)))
        {
            e.Handled = true;
            SendMessage();
        }
    }

    private void NewChat_Click(object sender, RoutedEventArgs e)
    {
        if (_currentSid != null && !_streaming) _ = _chat.SendNewChat();
    }

    private void SessionList_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_suppressSelect || _streaming) return;
        if (SessionList.SelectedItem is ListViewItem item && item.Tag is string sid && sid != _currentSid)
        {
            _ = _chat.SendSwitch(sid);
        }
    }

    private async void Settings_Click(object sender, RoutedEventArgs e) => OpenSettingsDialog(false);

    private async void OpenSettingsDialog(bool firstRun)
    {
        if (_projectRoot == null)
        {
            ShowInlineError("未找到项目根目录, 无法保存设置。");
            return;
        }
        var dialog = new SettingsDialog(_settings, firstRun)
        {
            XamlRoot = Content.XamlRoot,
            RequestedTheme = UiColors.IsDarkTheme ? ElementTheme.Dark : ElementTheme.Light,
        };
        var result = await dialog.ShowAsync();
        if (result != ContentDialogResult.Primary || dialog.Result == null) return;
        await ApplySettingsAsync(dialog.Result);
    }

    private async Task ApplySettingsAsync(GuiSettings next)
    {
        var old = _settings;
        _settings = next;
        _settings.Save(_projectRoot!);
        _fontSize = _settings.FontSize;
        UiColors.Apply(_settings.Accent, _settings.Background);
        ApplyDisplaySettings();

        if (_settings.BackendChanged(old))
        {
            if (_serverProcess != null)
            {
                ShowInlineError("后端配置已变更, 正在重启后端…");
                try { if (!_serverProcess.HasExited) _serverProcess.Kill(); } catch { }
                _serverProcess = null;
                var (ok, reason) = await EnsureServerAsync();
                if (!ok)
                {
                    ShowInlineError("后端重启失败: " + reason);
                    return;
                }
                try { _chat.Close(); } catch { }
                await _chat.ConnectAsync($"ws://127.0.0.1:{_port}/ws");
                await _chat.SendNewChat();
                SetStatus("已连接", false);
            }
            else
            {
                ShowInlineError("后端配置已保存; 若后端是外部启动的 (webui.bat), 请手动重启后再生效。");
            }
        }
    }

    private void ApplyDisplaySettings()
    {
        ApplyTheme();
        ModelBadge.Text = _settings.Model;
        SidebarFooter.Text = $"模型: {_settings.Model}\n工具: 15 个系统级 MCP";
    }

    /// <summary>按当前配色给静态 XAML 元素换肤 (消息气泡等动态元素直接用 UiColors)。</summary>
    private void ApplyTheme()
    {
        try
        {
            RootGrid.RequestedTheme = UiColors.IsDarkTheme ? ElementTheme.Dark : ElementTheme.Light;
            RootGrid.Background = UiColors.Brush(UiColors.Background);
            SidebarPanel.Background = UiColors.Brush(UiColors.Panel);
            SidebarPanel.BorderBrush = UiColors.Brush(UiColors.Border);
            HeaderPanel.Background = UiColors.Brush(UiColors.Panel);
            HeaderPanel.BorderBrush = UiColors.Brush(UiColors.Border);
            InputPanel.Background = UiColors.Brush(UiColors.Panel);
            InputPanel.BorderBrush = UiColors.Brush(UiColors.Border);
            NewChatBtn.Background = UiColors.Brush(UiColors.Panel2);
            NewChatBtn.BorderBrush = UiColors.Brush(UiColors.Border);
            NewChatBtn.Foreground = UiColors.Brush(UiColors.Text);
            SettingsBtn.Background = UiColors.Brush(UiColors.Panel2);
            SettingsBtn.BorderBrush = UiColors.Brush(UiColors.Border);
            SettingsBtn.Foreground = UiColors.Brush(UiColors.Muted);
            SendBtn.Background = UiColors.Brush(UiColors.AccentDark);
            ModelBadgeBorder.Background = UiColors.Brush(UiColors.BadgeBg);
            StatusText.Foreground = UiColors.Brush(UiColors.Muted);
            SidebarFooter.Foreground = UiColors.Brush(UiColors.Muted);
            InputBox.Background = UiColors.Brush(UiColors.Panel2);
            InputBox.BorderBrush = UiColors.Brush(UiColors.Border);
            InputBox.Foreground = UiColors.Brush(UiColors.Text);
        }
        catch
        {
            // 个别控件不可用时忽略, 不影响主流程
        }
    }

    private void SendMessage()
    {
        var text = InputBox.Text.Trim();
        if (string.IsNullOrEmpty(text) || _currentSid == null || _streaming) return;
        InputBox.Text = "";
        AddUserMessage(text);
        _acc = "";
        _assistantContent = null;
        _assistantTools = null;
        _lastResultText = null;
        _streaming = true;
        SetStatus("正在思考…", true);
        _ = _chat.SendChat(_currentSid, text);
    }
}
