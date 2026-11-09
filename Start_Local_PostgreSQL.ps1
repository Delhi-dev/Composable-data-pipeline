param(
    [string]$DatabaseHost = "localhost",
    [int]$DatabasePort = 5432,
    [string]$DatabaseName = "cbcr",
    [string]$DatabaseUser = "cbcr_user",
    [int]$WebPort = 8000
)

$ErrorActionPreference = "Stop"
$repositoryRoot = $PSScriptRoot
$passwordWasAlreadySet = -not [string]::IsNullOrWhiteSpace($env:CBCR_SOURCE_DB_PASSWORD)

$env:CBCR_PERSISTENCE_BACKEND = "postgresql"
$env:CBCR_PG_HOST = $DatabaseHost
$env:CBCR_PG_PORT = [string]$DatabasePort
$env:CBCR_PG_DATABASE = $DatabaseName
$env:CBCR_PG_USER = $DatabaseUser
$env:CBCR_PG_PASSWORD_ENV = "CBCR_SOURCE_DB_PASSWORD"
$env:CBCR_UI_IMPERSONATION = "1"

if (-not $passwordWasAlreadySet) {
    $securePassword = Read-Host "Password for PostgreSQL role $DatabaseUser" -AsSecureString
    $passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
    try {
        $env:CBCR_SOURCE_DB_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR(
            $passwordPointer
        )
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
    }
}

Write-Host "Starting CbCR risk-to-case v2 on http://127.0.0.1:$WebPort/"
Write-Host "Swagger: http://127.0.0.1:$WebPort/docs"
Write-Host "Database: ${DatabaseHost}:${DatabasePort}/${DatabaseName} as $DatabaseUser"

try {
    Set-Location -LiteralPath $repositoryRoot
    python -m uvicorn --app-dir platform cbcr_backend:app --host 127.0.0.1 --port $WebPort
}
finally {
    if (-not $passwordWasAlreadySet) {
        Remove-Item Env:CBCR_SOURCE_DB_PASSWORD -ErrorAction SilentlyContinue
    }
}
