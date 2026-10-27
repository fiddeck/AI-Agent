// AI-Agent Launcher (C++ / Win32)
// 双击即可启动: 以 exe 所在目录为基准向上查找项目根目录 (需同时包含
// .venv\Scripts\python.exe 与 chat.py), 然后在新控制台窗口中运行
// .venv\Scripts\python.exe chat.py。
// 不依赖"当前工作目录", 因此从资源管理器里直接双击本程序也能正常运行。
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <filesystem>
#include <string>

namespace fs = std::filesystem;

// 以 Windows 子系统链接 (无控制台窗口), 但仍从 main() 进入
#pragma comment(linker, "/SUBSYSTEM:WINDOWS /ENTRY:mainCRTStartup")

// 从 exe 所在目录向上查找项目根目录 (最多 10 层)
static fs::path FindProjectRoot()
{
    wchar_t buf[MAX_PATH * 2] = { 0 };
    DWORD n = GetModuleFileNameW(nullptr, buf, MAX_PATH * 2);
    if (n == 0 || n >= MAX_PATH * 2) return {};

    fs::path dir = fs::path(buf).parent_path();
    for (int i = 0; i < 10 && !dir.empty(); ++i, dir = dir.parent_path())
    {
        if (fs::exists(dir / L".venv" / L"Scripts" / L"python.exe") &&
            fs::exists(dir / L"chat.py"))
            return dir;
    }
    return {};
}

static void FailBox(const std::wstring& msg)
{
    MessageBoxW(nullptr, msg.c_str(), L"AI-Agent 启动器", MB_OK | MB_ICONERROR);
}

int main()
{
    fs::path root = FindProjectRoot();
    if (root.empty())
    {
        FailBox(L"未找到项目根目录 (需要同时包含 .venv\\Scripts\\python.exe 和 chat.py)。\n"
                L"请把本程序放在项目目录内或它的子目录中。");
        return 1;
    }

    fs::path python = root / L".venv" / L"Scripts" / L"python.exe";
    if (!fs::exists(python))
    {
        FailBox(L"找不到虚拟环境: " + python.wstring() +
                L"\n请先在项目根目录执行 uv sync 安装依赖。");
        return 1;
    }

    fs::path script = root / L"chat.py";
    // 用 cmd /k 启动: 新开控制台窗口, 程序退出后窗口保留以便查看报错
    std::wstring cmdline = L"/k \"\"" + python.wstring() + L"\" \"" + script.wstring() + L"\"\"";

    STARTUPINFOW si{ sizeof(si) };
    PROCESS_INFORMATION pi{};
    BOOL ok = CreateProcessW(L"C:\\Windows\\System32\\cmd.exe", cmdline.data(),
                             nullptr, nullptr, FALSE, CREATE_NEW_CONSOLE,
                             nullptr, root.wstring().c_str(), &si, &pi);
    if (!ok)
    {
        FailBox(L"启动失败, 错误码: " + std::to_wstring(GetLastError()));
        return 1;
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
