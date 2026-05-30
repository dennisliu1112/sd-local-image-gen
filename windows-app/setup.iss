#define AppName "Z-Image Generator"
#define AppVersion "1.0"
#define AppPublisher "ZImageGen"
#define AppURL "https://github.com/dennisliu1112/sd-local-image-gen"
#define AppExeName "start.bat"

[Setup]
AppId={{F3A2B1C4-8D5E-4F6A-9B0C-1D2E3F4A5B6C}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
DefaultDirName={autopf}\ZImageGen
DefaultGroupName={#AppName}
AllowNoIcons=yes
OutputDir=installer_out
OutputBaseFilename=ZImageGen_Setup_{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
ModelDirLabel=Model folder (where to store or find the 6.3 GB model files):
ModelDirHint=If you already have the models downloaded, point to that folder.

[Code]
var
  ModelDirPage: TInputDirWizardPage;

procedure InitializeWizard;
begin
  ModelDirPage := CreateInputDirPage(
    wpSelectDir,
    'Select Model Folder',
    'Where are your model files, or where should they be downloaded?',
    'Select the folder containing (or to receive) the model files.'#13#10 +
    'Required files: z_image_turbo-Q4_K.gguf, ae.safetensors, Qwen3-4B-Q4_K_M.gguf',
    False, '');
  ModelDirPage.Add('');
  ModelDirPage.Values[0] := ExpandConstant('{localappdata}\ZImageGen\models');
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ConfigPath, ModelDir, EscapedDir, JsonContent: String;
begin
  if CurStep = ssPostInstall then
  begin
    ModelDir := ModelDirPage.Values[0];
    if not DirExists(ModelDir) then
      ForceDirectories(ModelDir);

    ConfigPath := ExpandConstant('{app}\config.json');
    EscapedDir := ModelDir;
    StringChangeEx(EscapedDir, '\', '\\', True);
    JsonContent := '{"model_dir": "' + EscapedDir + '"}';
    SaveStringToFile(ConfigPath, JsonContent, False);
  end;
end;

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\start.bat"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#AppName}"; Filename: "{app}\start.bat"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\start.bat"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent shellexec
