; Custom NSIS hooks for Amazing image Generator
; -----------------------------------------------------------------------------
; Goal 1 — force an all-ASCII install directory (C:\AiG).
;   The app downloads its engine + model files into the install dir at runtime,
;   and the underlying sd-server uses a narrow-char file API that breaks on
;   non-ASCII paths (e.g. 桌面 / 下載). Pinning the install root to C:\AiG
;   removes that whole class of failure regardless of the user's locale.
;
; Goal 2 — keep C:\AiG writable for the (non-elevated) running app.
;   The installer is elevated (perMachine, writes under C:\). Without an ACL
;   grant, a standard user running the app afterwards could not write
;   models/, engine-*/, config.json or logs/ into the install dir.
; -----------------------------------------------------------------------------

; electron-builder reads InstallLocation from the registry when resolving the
; default $INSTDIR. Writing it here (before init) pins the directory to C:\AiG.
!macro preInit
  SetRegView 64
  WriteRegExpandStr HKLM "${INSTALL_REGISTRY_KEY}" InstallLocation "C:\AiG"
  WriteRegExpandStr HKCU "${INSTALL_REGISTRY_KEY}" InstallLocation "C:\AiG"
  SetRegView 32
  WriteRegExpandStr HKLM "${INSTALL_REGISTRY_KEY}" InstallLocation "C:\AiG"
  WriteRegExpandStr HKCU "${INSTALL_REGISTRY_KEY}" InstallLocation "C:\AiG"
!macroend

!macro customInstall
  ; Grant BUILTIN\Users (SID S-1-5-32-545) Modify rights, inherited by
  ; subfolders/files, so the running app can download engines + models and
  ; write its config/logs into C:\AiG without elevation.
  nsExec::Exec 'icacls "$INSTDIR" /grant *S-1-5-32-545:(OI)(CI)M /T'
!macroend
