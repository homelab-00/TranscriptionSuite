; ==============================================================
; AutoHotkey Script for Speech-to-Text Hotkey Control
; ==============================================================

#NoEnv
#SingleInstance Force
SendMode Input
SetWorkingDir %A_ScriptDir%

; Check if ncat is available and use a suitable command
CheckNetCatCmd() {
    ; Check if ncat is available
    RunWait, %comspec% /c ncat --version, , Hide UseErrorLevel
    if (ErrorLevel = 0) {
        return "ncat"
    }
    
    ; Check if nc is available
    RunWait, %comspec% /c nc --version, , Hide UseErrorLevel
    if (ErrorLevel = 0) {
        return "nc"
    }
    
    ; If neither is available, use PowerShell for TCP communication
    return "powershell"
}

; Function to send command using the available method
SendCommand(command) {
    static netcatCmd := CheckNetCatCmd()
    
    if (netcatCmd = "ncat") {
        RunWait, %comspec% /c echo %command% | ncat 127.0.0.1 35000, , Hide
    } 
    else if (netcatCmd = "nc") {
        RunWait, %comspec% /c echo %command% | nc 127.0.0.1 35000, , Hide
    }
    else {
        ; Use PowerShell as a fallback
        psCmd := "powershell.exe -Command ""$client = New-Object System.Net.Sockets.TCPClient('127.0.0.1', 35000); $stream = $client.GetStream(); $writer = New-Object System.IO.StreamWriter($stream); $writer.WriteLine('" command "'); $writer.Flush(); $client.Close()"""
        RunWait, %psCmd%, , Hide
    }
}

; F1 - Open Configuration Dialog
*F1::
    SendCommand("OPEN_CONFIG")
return

; F2 - Toggle Real-time Transcription
*F2::
    SendCommand("TOGGLE_REALTIME")
return

; F3 - Start Long-form Recording
*F3::
    SendCommand("START_LONGFORM")
return

; F4 - Stop Long-form Recording and Transcribe
*F4::
    SendCommand("STOP_LONGFORM")
return

; F10 - Open Static File Transcription
*F10::
    SendCommand("RUN_STATIC")
return

; F7 - Quit Application
*F7::
    SendCommand("QUIT")
return