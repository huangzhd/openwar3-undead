// Experimental adapter for the pinned 2026.09.26.1644 OpenWar3 runtime.
// Uses the same WH_GETMESSAGE/bootstrap contract observed in war3_launch.exe.
// No game-file replacement, remote memory patching, privilege adjustment or game exit.
using System;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;

class RuntimeAttach {
    const string RuntimeHash = "92bb7e6b75e56f91e7eb905844b9a28085e88d4d991a547522c7da8c2907da97";
    const uint ControlSize = 0xf9b4;
    delegate bool EnumProc(IntPtr hwnd, IntPtr value);
    [DllImport("kernel32", SetLastError=true)] static extern IntPtr OpenProcess(uint access, bool inherit, uint pid);
    [DllImport("kernel32", SetLastError=true)] static extern bool GetProcessTimes(IntPtr p, out long created, out long exited, out long kernel, out long user);
    [DllImport("kernel32", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool QueryFullProcessImageNameW(IntPtr p,uint flags,StringBuilder text,ref uint size);
    [DllImport("kernel32", CharSet=CharSet.Unicode, SetLastError=true)] static extern IntPtr LoadLibraryW(string path);
    [DllImport("kernel32", CharSet=CharSet.Ansi, SetLastError=true)] static extern IntPtr GetProcAddress(IntPtr module,string name);
    [DllImport("kernel32", CharSet=CharSet.Unicode, SetLastError=true)] static extern IntPtr CreateFileMappingW(IntPtr file,IntPtr sa,uint protection,uint high,uint low,string name);
    [DllImport("kernel32", CharSet=CharSet.Unicode, SetLastError=true)] static extern IntPtr OpenFileMappingW(uint access,bool inherit,string name);
    [DllImport("kernel32", CharSet=CharSet.Unicode, SetLastError=true)] static extern IntPtr CreateEventW(IntPtr sa,bool manual,bool initial,string name);
    [DllImport("kernel32", CharSet=CharSet.Unicode, SetLastError=true)] static extern IntPtr CreateMutexW(IntPtr sa,bool owner,string name);
    [DllImport("kernel32", SetLastError=true)] static extern uint WaitForSingleObject(IntPtr handle,uint ms);
    [DllImport("kernel32")] static extern bool CloseHandle(IntPtr handle);
    [DllImport("shell32")] static extern bool IsUserAnAdmin();
    [DllImport("user32", SetLastError=true)] static extern bool EnumWindows(EnumProc callback,IntPtr value);
    [DllImport("user32", CharSet=CharSet.Unicode)] static extern int GetClassNameW(IntPtr hwnd,StringBuilder text,int count);
    [DllImport("user32", SetLastError=true)] static extern uint GetWindowThreadProcessId(IntPtr hwnd,out uint pid);
    [DllImport("user32", CharSet=CharSet.Unicode, SetLastError=true)] static extern IntPtr SetWindowsHookExW(int hook,IntPtr callback,IntPtr module,uint thread);
    [DllImport("user32", SetLastError=true)] static extern bool UnhookWindowsHookEx(IntPtr hook);
    [DllImport("user32", CharSet=CharSet.Unicode, SetLastError=true)] static extern uint RegisterWindowMessageW(string name);
    [DllImport("user32", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool PostThreadMessageW(uint thread,uint message,UIntPtr wparam,IntPtr lparam);
    [DllImport("user32", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool PostMessageW(IntPtr hwnd,uint message,UIntPtr wparam,IntPtr lparam);

    static string stage = "arguments";
    static void Check(bool condition,string operation) {
        if (!condition) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(),operation);
    }
    static string Hash(string path) {
        using (var s=File.OpenRead(path)) using(var h=SHA256.Create())
            return BitConverter.ToString(h.ComputeHash(s)).Replace("-", "").ToLowerInvariant();
    }
    static bool Exists(string name) {
        IntPtr h=OpenFileMappingW(4,false,name);
        if(h!=IntPtr.Zero) {CloseHandle(h);return true;}
        int e=Marshal.GetLastWin32Error();
        if(e!=2) throw new System.ComponentModel.Win32Exception(e,"Inspect existing IPC");
        return false;
    }
    static void Fresh(IntPtr h,string name) {
        int error=Marshal.GetLastWin32Error();
        if(h==IntPtr.Zero) throw new System.ComponentModel.Win32Exception(error,name);
        if(error==183) throw new InvalidOperationException("Existing bootstrap object: "+name);
    }
    static int Main(string[] args) {
        Console.OutputEncoding=new UTF8Encoding(false);
        if(args.Length==1 && args[0]=="--self-check") {
            Console.WriteLine("runtime-attach x86="+(IntPtr.Size==4)+" control-size="+ControlSize);
            return IntPtr.Size==4 ? 0 : 1;
        }
        IntPtr process=IntPtr.Zero,ready=IntPtr.Zero,control=IntPtr.Zero,done=IntPtr.Zero,mutex=IntPtr.Zero,hook=IntPtr.Zero;
        // The DLL deliberately pins itself after initialization. Do not unload it
        // from the game or send Remove while a live SDK client may be using it.
        try {
            if(args.Length!=6 || IntPtr.Size!=4) throw new ArgumentException("Usage: RuntimeAttach PID CREATED_UNIX EXE DLL GAME_DLL_SHA256 STOP_FILE (x86 only)");
            uint pid=uint.Parse(args[0]);
            double expected=double.Parse(args[1],CultureInfo.InvariantCulture);
            string exe=Path.GetFullPath(args[2]),dll=Path.GetFullPath(args[3]),stop=Path.GetFullPath(args[5]);
            Console.WriteLine("loader_elevated="+IsUserAnAdmin());Console.Out.Flush();
            stage="validate_files";
            if(Hash(dll)!=RuntimeHash) throw new InvalidOperationException("Runtime SHA256 mismatch");
            string gameDll=Path.Combine(Path.GetDirectoryName(exe),"Game.dll");
            if(Hash(gameDll)!=args[4]) throw new InvalidOperationException("Game.dll SHA256 mismatch");
            var version=FileVersionInfo.GetVersionInfo(gameDll);
            if(version.FileMajorPart!=1 || version.FileMinorPart!=27 || version.FileBuildPart!=0 || version.FilePrivatePart!=52240)
                throw new InvalidOperationException("Unsupported Game.dll version");
            stage="validate_process";
            process=OpenProcess(0x101000,false,pid); Check(process!=IntPtr.Zero,"OpenProcess(query/synchronize)");
            long created,exited,kernel,user;
            Check(GetProcessTimes(process,out created,out exited,out kernel,out user),"GetProcessTimes");
            double actual=(created-116444736000000000L)/10000000.0;
            if(Math.Abs(expected-actual)>0.001) throw new InvalidOperationException("PID identity changed");
            uint length=32768;var image=new StringBuilder((int)length);
            Check(QueryFullProcessImageNameW(process,0,image,ref length),"QueryFullProcessImageName");
            if(!String.Equals(exe,Path.GetFullPath(image.ToString()),StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Target executable mismatch");
            if(Exists("Local\\War3World_"+pid) || Exists("Local\\War3UiControl_"+pid))
                throw new InvalidOperationException("Runtime or bootstrap already exists; refusing duplicate installation");
            stage="wait_game_window";
            IntPtr window=IntPtr.Zero;uint thread=0;
            var timer=Stopwatch.StartNew();
            while(window==IntPtr.Zero && timer.Elapsed.TotalSeconds<45) {
                if(File.Exists(stop)) return 0;
                if(WaitForSingleObject(process,0)==0) throw new InvalidOperationException("Game exited before initialization");
                EnumWindows(delegate(IntPtr hwnd,IntPtr unused) {
                    uint owner;uint tid=GetWindowThreadProcessId(hwnd,out owner);
                    if(owner!=pid) return true;
                    var name=new StringBuilder(256);GetClassNameW(hwnd,name,256);
                    if(name.ToString()=="Warcraft III") {window=hwnd;thread=tid;return false;}
                    return true;
                },IntPtr.Zero);
                if(window==IntPtr.Zero) Thread.Sleep(100);
            }
            if(window==IntPtr.Zero) throw new TimeoutException("No Warcraft III window in 45 seconds");
            Console.WriteLine("target_window="+window+" thread="+thread+" pid="+pid);Console.Out.Flush();
            stage="create_bootstrap";
            ready=CreateEventW(IntPtr.Zero,true,false,"Local\\War3RenderHookReady_"+pid);Fresh(ready,"ready event");
            control=CreateFileMappingW(new IntPtr(-1),IntPtr.Zero,4,0,ControlSize,"Local\\War3UiControl_"+pid);Fresh(control,"control mapping");
            done=CreateEventW(IntPtr.Zero,true,false,"Local\\War3UiControlDone_"+pid);Fresh(done,"done event");
            mutex=CreateMutexW(IntPtr.Zero,false,"Local\\War3UiControlMutex_"+pid);Fresh(mutex,"control mutex");
            // Newly created pagefile mapping is zeroed by Windows; never zero an existing block.
            stage="load_runtime_in_helper";
            IntPtr module=LoadLibraryW(dll);Check(module!=IntPtr.Zero,"LoadLibraryW");
            IntPtr callback=GetProcAddress(module,"_War3RenderHookProc@12");Check(callback!=IntPtr.Zero,"GetProcAddress");
            stage="install_thread_hook";
            hook=SetWindowsHookExW(3,callback,module,thread);Check(hook!=IntPtr.Zero,"SetWindowsHookExW(WH_GETMESSAGE)");
            Console.WriteLine("thread_hook_registered; runtime_initialization_not_yet_confirmed");Console.Out.Flush();
            stage="initialization_handshake";
            uint message=RegisterWindowMessageW("War3RenderHook.InstallNative.v1");Check(message!=0,"RegisterWindowMessageW");
            Check(PostThreadMessageW(thread,message,new UIntPtr(unchecked((uint)window.ToInt32())),IntPtr.Zero),"PostThreadMessageW");
            Check(PostMessageW(window,0,UIntPtr.Zero,IntPtr.Zero),"PostMessageW(WM_NULL)");
            uint result=WaitForSingleObject(ready,10000);
            if(result!=0) throw new TimeoutException("Runtime handshake wait result="+result);
            Console.WriteLine("handshake_ready pid="+pid);Console.Out.Flush();
            stage="hold_hook";
            while(!File.Exists(stop)) {
                uint wait=WaitForSingleObject(process,200);
                if(wait==0) break;
                if(wait!=258) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(),"WaitForSingleObject");
            }
            Console.WriteLine("holder_stopped game_not_terminated");
            return 0;
        } catch(Exception ex) {
            var nativeError=ex as System.ComponentModel.Win32Exception;
            if(nativeError!=null) Console.Error.WriteLine("stage="+stage+" winerror="+nativeError.NativeErrorCode);
            Console.Error.WriteLine("stage="+stage+" error="+ex.ToString());
            return 1;
        } finally {
            if(hook!=IntPtr.Zero) UnhookWindowsHookEx(hook);
            foreach(IntPtr h in new[]{mutex,done,control,ready,process}) if(h!=IntPtr.Zero) CloseHandle(h);
        }
    }
}
