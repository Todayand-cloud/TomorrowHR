' 서버가 꺼져 있으면 백그라운드로 기동 (브라우저 수동 갱신용)
Option Explicit
Dim sh, fso, root, xhr, cmd
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
root = fso.GetParentFolderName(root)

On Error Resume Next
Set xhr = CreateObject("MSXML2.XMLHTTP")
xhr.Open "GET", "http://127.0.0.1:8787/health", False
xhr.Send
If Err.Number = 0 Then
  If xhr.Status = 200 Then WScript.Quit 0
End If
Err.Clear
On Error GoTo 0

cmd = "py -3 """ & root & "\_law_fetch\refresh_server.py"" --no-browser"
sh.Run cmd, 0, False
WScript.Sleep 1200
