# Makes store/meet-helper.zip from the extension folder, for the Chrome Web Store upload.
# Raise "version" in extension/manifest.json before every new upload.
# (Not Compress-Archive: in Windows PowerShell 5.1 it writes "icons\icon16.png" with a
# backslash, which the store does not accept. Here the paths use "/".)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
$extension = (Resolve-Path (Join-Path $PSScriptRoot '..\extension')).Path
$zipPath = Join-Path $PSScriptRoot 'meet-helper.zip'
if (Test-Path $zipPath) { Remove-Item $zipPath }

$zip = [System.IO.Compression.ZipFile]::Open($zipPath, 'Create')
try {
    Get-ChildItem $extension -Recurse -File | ForEach-Object {
        $name = $_.FullName.Substring($extension.Length + 1).Replace('\', '/')
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $_.FullName, $name) | Out-Null
    }
} finally { $zip.Dispose() }
Write-Host "Made $zipPath"
