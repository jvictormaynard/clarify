param([Parameter(Mandatory = $true)][string]$CommandJson)
$ErrorActionPreference = 'Stop'
# Windows Job Objects keep ownership after the test runner itself exits.
# Start suspended so no descendant can escape before assignment. The handle is
# private and non-inheritable. Closing this helper also kills the owned job.
Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
public static class ClarifyTestJob {
    [StructLayout(LayoutKind.Sequential)] struct BasicLimits {
        public long ProcessTime, JobTime;
        public uint Flags;
        public UIntPtr MinWorkingSet, MaxWorkingSet;
        public uint ActiveLimit;
        public UIntPtr Affinity;
        public uint Priority, Scheduling;
    }
    [StructLayout(LayoutKind.Sequential)] struct IO {
        public ulong ReadOps, WriteOps, OtherOps, ReadBytes, WriteBytes, OtherBytes;
    }
    [StructLayout(LayoutKind.Sequential)] struct Limits {
        public BasicLimits Basic; public IO IO;
        public UIntPtr ProcessMemory, JobMemory, PeakProcessMemory, PeakJobMemory;
    }
    [StructLayout(LayoutKind.Sequential)] struct Accounting {
        public long User, Kernel, PeriodUser, PeriodKernel;
        public uint Faults, Total, Active, Terminated;
    }
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] struct Startup {
        public uint Size; public string Reserved, Desktop, Title;
        public uint X, Y, Width, Height, CharsX, CharsY, Fill, Flags;
        public ushort Show, ReservedSize; public IntPtr ReservedBytes, In, Out, Error;
    }
    [StructLayout(LayoutKind.Sequential)] struct ProcessInfo {
        public IntPtr Process, Thread; public uint ProcessId, ThreadId;
    }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern IntPtr CreateJobObject(IntPtr attributes, string name);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool SetInformationJobObject(IntPtr job, int type, ref Limits data, uint size);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool QueryInformationJobObject(IntPtr job, int type, out Accounting data, uint size, IntPtr length);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool TerminateJobObject(IntPtr job, uint code);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool TerminateProcess(IntPtr process, uint code);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool CreateProcess(string file, StringBuilder command, IntPtr processAttributes, IntPtr threadAttributes, bool inherit, uint flags, IntPtr environment, string cwd, ref Startup startup, out ProcessInfo info);
    [DllImport("kernel32.dll", SetLastError=true)] static extern uint ResumeThread(IntPtr thread);
    [DllImport("kernel32.dll", SetLastError=true)] static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetExitCodeProcess(IntPtr process, out uint code);
    [DllImport("kernel32.dll")] static extern IntPtr GetStdHandle(int kind);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
    static void Check(bool value) { if (!value) throw new Win32Exception(Marshal.GetLastWin32Error()); }
    static string Quote(string value) {
        if (value == null || value.IndexOf('\0') >= 0) throw new ArgumentException("Invalid process argument");
        StringBuilder result = new StringBuilder("\""); int slashes = 0;
        foreach (char c in value) {
            if (c == '\\') { slashes++; continue; }
            if (c == '"') result.Append('\\', slashes * 2 + 1);
            else result.Append('\\', slashes);
            result.Append(c); slashes = 0;
        }
        return result.Append('\\', slashes * 2).Append('"').ToString();
    }
    public static int Run(string file, string[] args) {
        IntPtr job = CreateJobObject(IntPtr.Zero, null);
        Check(job != IntPtr.Zero); ProcessInfo process = new ProcessInfo();
        try {
            Limits limits = new Limits(); limits.Basic.Flags = 0x2000; // KILL_ON_JOB_CLOSE
            Check(SetInformationJobObject(job, 9, ref limits, (uint)Marshal.SizeOf(typeof(Limits))));
            StringBuilder command = new StringBuilder(Quote(file));
            foreach (string arg in args) command.Append(' ').Append(Quote(arg));
            if (command.Length >= 32767) throw new ArgumentException("Process command is too long");
            Startup startup = new Startup(); startup.Size = (uint)Marshal.SizeOf(typeof(Startup));
            startup.Flags = 0x100; startup.In = GetStdHandle(-10); startup.Out = GetStdHandle(-11); startup.Error = GetStdHandle(-12);
            Check(CreateProcess(file, command, IntPtr.Zero, IntPtr.Zero, true, 0x08000004, IntPtr.Zero, Environment.CurrentDirectory, ref startup, out process));
            try {
                Check(AssignProcessToJobObject(job, process.Process));
                Check(ResumeThread(process.Thread) != UInt32.MaxValue);
            } catch { TerminateProcess(process.Process, 1); throw; }
            Check(WaitForSingleObject(process.Process, UInt32.MaxValue) == 0);
            uint code; Check(GetExitCodeProcess(process.Process, out code));
            Check(TerminateJobObject(job, 1));
            for (int attempt = 0; attempt < 1000; attempt++) {
                Accounting state;
                Check(QueryInformationJobObject(job, 1, out state, (uint)Marshal.SizeOf(typeof(Accounting)), IntPtr.Zero));
                if (state.Active == 0) return unchecked((int)code);
                Thread.Sleep(10);
            }
            throw new TimeoutException("Owned test descendants did not stop");
        } finally {
            if (process.Thread != IntPtr.Zero) CloseHandle(process.Thread);
            if (process.Process != IntPtr.Zero) CloseHandle(process.Process);
            CloseHandle(job);
        }
    }
}
'@
$request = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($CommandJson)) | ConvertFrom-Json
exit [ClarifyTestJob]::Run([string]$request.file, [string[]]$request.arguments)
