param([string]$Script, [string]$Log, [string[]]$ScriptArgs = @())
$runnerRoot = $PSScriptRoot
$jobStart = [System.Diagnostics.ProcessStartInfo]::new()
$jobStart.FileName = 'D:\Users\13957\anaconda3\python.exe'
$jobStart.WorkingDirectory = $runnerRoot
$jobStart.UseShellExecute = $false
$jobStart.CreateNoWindow = $true
$jobStart.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
$jobStart.ArgumentList.Add('-X')
$jobStart.ArgumentList.Add('utf8')
$jobStart.ArgumentList.Add('-c')
$jobStart.ArgumentList.Add('import runpy,sys; script,log,*args=sys.argv[1:]; sys.stdout=open(log,"w",encoding="utf-8",buffering=1); sys.stderr=sys.stdout; sys.argv=[script,*args]; runpy.run_path(script,run_name="__main__")')
$jobStart.ArgumentList.Add($Script)
$jobStart.ArgumentList.Add($Log)
foreach ($scriptArg in $ScriptArgs) { $jobStart.ArgumentList.Add($scriptArg) }
$jobProc = [System.Diagnostics.Process]::Start($jobStart)
[pscustomobject]@{Pid=$jobProc.Id; MainWindowHandle=$jobProc.MainWindowHandle; Log=$Log}
