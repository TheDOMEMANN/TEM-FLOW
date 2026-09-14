Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
folder = files.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = folder
shell.Run Chr(34) & folder & "\runtime\pythonw.exe" & Chr(34) & " " & Chr(34) & folder & "\desktop_launcher.py" & Chr(34), 0, False
