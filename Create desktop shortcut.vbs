Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
folder = files.GetParentFolderName(WScript.ScriptFullName)
Set shortcut = shell.CreateShortcut(shell.SpecialFolders("Desktop") & "\TEM-FLOW.lnk")
shortcut.TargetPath = folder & "\runtime\pythonw.exe"
shortcut.Arguments = Chr(34) & folder & "\desktop_launcher.py" & Chr(34)
shortcut.WorkingDirectory = folder
shortcut.Description = "TEM-FLOW editable local desktop engine"
shortcut.IconLocation = folder & "\runtime\pythonw.exe,0"
shortcut.Save
WScript.Echo "TEM-FLOW shortcut created on your desktop."
