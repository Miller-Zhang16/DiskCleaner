/* DiskCleaner.exe — 极简 C 启动器。
 * 功能：
 *   1) 获取自身所在目录（exe 放在便携包根，与 python-embed/ 同级）
 *   2) 设置 TCL_LIBRARY / TK_LIBRARY 环境变量
 *   3) CreateProcess 启动 python-embed\pythonw.exe main.py（无黑窗口）
 * 优点：纯原生代码、不解压、不运行时拼接字节码，AV 不会当它可疑。
 */

#include <windows.h>
#include <stdio.h>

int main(void)
{
    char self[MAX_PATH];
    char dir[MAX_PATH];
    char tcl[MAX_PATH], tk[MAX_PATH];
    char python[MAX_PATH];
    char cmdline[MAX_PATH * 2];

    /* 1) 自身完整路径 */
    DWORD n = GetModuleFileNameA(NULL, self, MAX_PATH);
    if (n == 0 || n >= MAX_PATH)
        return 1;

    /* 2) 取目录（去掉 exe 文件名）*/
    strncpy(dir, self, MAX_PATH);
    char *sl = strrchr(dir, '\\');
    if (sl) *sl = '\0';

    /* 3) 拼接环境变量与 pythonw.exe 路径 */
    _snprintf(tcl, sizeof(tcl), "%s\\python-embed\\tcl\\tcl8.6", dir);
    _snprintf(tk,  sizeof(tk),  "%s\\python-embed\\tcl\\tk8.6",  dir);
    _snprintf(python, sizeof(python), "%s\\python-embed\\pythonw.exe", dir);

    SetEnvironmentVariableA("TCL_LIBRARY", tcl);
    SetEnvironmentVariableA("TK_LIBRARY",  tk);

    /* 4) 命令行："pythonw.exe" "main.py"（主进程目录为自身所在目录）*/
    _snprintf(cmdline, sizeof(cmdline), "\"%s\" \"main.py\"", python);

    STARTUPINFOA si;
    PROCESS_INFORMATION pi;
    memset(&si, 0, sizeof(si));
    si.cb = sizeof(si);
    memset(&pi, 0, sizeof(pi));

    BOOL ok = CreateProcessA(
        python, cmdline, NULL, NULL, FALSE,
        CREATE_NO_WINDOW | DETACHED_PROCESS,
        NULL, dir, &si, &pi
    );
    if (ok) {
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
        return 0;
    }
    /* 回退：尝试 python.exe（便携包通常两个都有）*/
    _snprintf(python, sizeof(python), "%s\\python-embed\\python.exe", dir);
    _snprintf(cmdline, sizeof(cmdline), "\"%s\" \"main.py\"", python);
    ok = CreateProcessA(
        python, cmdline, NULL, NULL, FALSE,
        CREATE_NO_WINDOW | DETACHED_PROCESS,
        NULL, dir, &si, &pi
    );
    if (ok) {
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
        return 0;
    }
    return 1;
}
