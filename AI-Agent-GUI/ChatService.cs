using System;
using System.Collections.Generic;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace AIAgentGUI;

/// <summary>
/// 与本地 webui.py 后端通信的 WebSocket 客户端。
/// 协议与 webui.py 的 /ws 端点一一对应。
/// </summary>
public sealed class ChatService
{
    private ClientWebSocket? _ws;
    private readonly SemaphoreSlim _sendLock = new(1, 1);

    // 服务端 -> 客户端事件 (均在接收线程触发, 使用方需自行调度到 UI 线程)
    public event Action<string>? SessionChanged;                    // 新会话 sid
    public event Action<List<SessionInfo>>? SessionsUpdated;        // 会话列表
    public event Action<string, List<HistoryMessage>>? HistoryReceived; // sid + 历史
    public event Action<string>? TokenReceived;                     // 流式文本增量
    public event Action<string, string>? ToolCallReceived;          // 工具名 + 参数(JSON串)
    public event Action<string, string>? ToolResultReceived;        // 工具名 + 结果文本
    public event Action? TurnDone;
    public event Action<string>? ErrorReceived;
    public event Action? Disconnected;

    public async Task ConnectAsync(string uri)
    {
        _ws?.Dispose();
        _ws = new ClientWebSocket();
        await _ws.ConnectAsync(new Uri(uri), CancellationToken.None);
        _ = ReceiveLoopAsync();
    }

    public async Task SendNewChat() => await SendAsync("{\"type\":\"new_chat\"}");

    /// <summary>断开连接并释放 (设置变更重启后端后重连用)。</summary>
    public void Close()
    {
        try { _ws?.Abort(); } catch { }
        try { _ws?.Dispose(); } catch { }
        _ws = null;
    }

    public async Task SendSwitch(string sid) =>
        await SendAsync($"{{\"type\":\"switch\",\"sid\":{JsonSerializer.Serialize(sid)}}}");

    public async Task SendChat(string sid, string content) =>
        await SendAsync($"{{\"type\":\"chat\",\"sid\":{JsonSerializer.Serialize(sid)},\"content\":{JsonSerializer.Serialize(content)}}}");

    private async Task SendAsync(string json)
    {
        if (_ws == null || _ws.State != WebSocketState.Open) return;
        var bytes = Encoding.UTF8.GetBytes(json);
        await _sendLock.WaitAsync();
        try
        {
            await _ws.SendAsync(new ArraySegment<byte>(bytes),
                WebSocketMessageType.Text, true, CancellationToken.None);
        }
        finally
        {
            _sendLock.Release();
        }
    }

    private async Task ReceiveLoopAsync()
    {
        var buffer = new byte[256 * 1024];
        try
        {
            while (_ws != null && _ws.State == WebSocketState.Open)
            {
                var result = await _ws.ReceiveAsync(new ArraySegment<byte>(buffer), CancellationToken.None);
                if (result.MessageType == WebSocketMessageType.Close) break;
                if (result.MessageType != WebSocketMessageType.Text) continue;
                var json = Encoding.UTF8.GetString(buffer, 0, result.Count);
                try { HandleMessage(json); }
                catch { /* 单条消息解析失败则跳过 */ }
            }
        }
        catch
        {
            // 连接异常
        }
        Disconnected?.Invoke();
    }

    private void HandleMessage(string json)
    {
        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;
        var type = root.GetProperty("type").GetString();

        switch (type)
        {
            case "session":
                SessionChanged?.Invoke(root.GetProperty("sid").GetString()!);
                EmitSessions(root.GetProperty("sessions"));
                break;

            case "sessions":
                EmitSessions(root.GetProperty("list"));
                break;

            case "history":
            {
                var sid = root.GetProperty("sid").GetString()!;
                var list = new List<HistoryMessage>();
                foreach (var m in root.GetProperty("messages").EnumerateArray())
                {
                    var role = m.GetProperty("role").GetString() ?? "assistant";
                    var content = m.GetProperty("content").GetString() ?? "";
                    list.Add(new HistoryMessage(role, content));
                }
                HistoryReceived?.Invoke(sid, list);
                break;
            }

            case "token":
                TokenReceived?.Invoke(root.GetProperty("content").GetString() ?? "");
                break;

            case "tool_call":
            {
                var name = root.GetProperty("name").GetString() ?? "?";
                var args = root.GetProperty("arguments").GetString() ?? "";
                ToolCallReceived?.Invoke(name, args);
                break;
            }

            case "tool_result":
            {
                var name = root.GetProperty("name").GetString() ?? "?";
                var content = root.GetProperty("content").GetString() ?? "";
                ToolResultReceived?.Invoke(name, content);
                break;
            }

            case "done":
                TurnDone?.Invoke();
                break;

            case "error":
                ErrorReceived?.Invoke(root.GetProperty("message").GetString() ?? "未知错误");
                break;
        }
    }

    private void EmitSessions(JsonElement arr)
    {
        var list = new List<SessionInfo>();
        foreach (var s in arr.EnumerateArray())
        {
            var sid = s.GetProperty("sid").GetString() ?? "";
            var title = s.GetProperty("title").GetString() ?? "";
            list.Add(new SessionInfo(sid, title));
        }
        SessionsUpdated?.Invoke(list);
    }
}
