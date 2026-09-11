$ErrorActionPreference = "Stop"

$project = "autoassist-step3-acceptance"
$composeFiles = @("-f", "compose.yaml", "-f", "compose.acceptance.yaml")
$baseUrl = "http://127.0.0.1:18080"
$inventoryPath = (Resolve-Path "docs/context/inventory/data.csv").Path

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & docker compose -p $project @composeFiles @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose command failed with exit code $LASTEXITCODE."
    }
}

function Wait-Healthy {
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            $health = Invoke-RestMethod "$baseUrl/health" -TimeoutSec 2
            if ($health.status -eq "ok") {
                return
            }
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    throw "Disposable acceptance backend did not become healthy."
}

try {
    Invoke-Compose build backend
    Invoke-Compose run --rm --no-deps --volume "${inventoryPath}:/tmp/inventory.csv:ro" backend `
        autoassist-import-inventory --file /tmp/inventory.csv --dealership mia-motors `
        --server-stopped
    Invoke-Compose up --detach backend
    Wait-Healthy

    $dealerships = Invoke-RestMethod "$baseUrl/dealerships"
    $dealershipId = ($dealerships.items | Where-Object slug -eq "mia-motors").id
    if (-not $dealershipId) {
        throw "mia-motors was not returned by the API."
    }

    $conversation = Invoke-RestMethod -Method Post `
        "$baseUrl/dealerships/$dealershipId/conversations" `
        -ContentType "application/json" -Body "{}"
    $conversationId = $conversation.id
    $messagesUrl = "$baseUrl/dealerships/$dealershipId/conversations/$conversationId/messages"

    $searchRequestId = [guid]::NewGuid().ToString()
    $searchBody = @{ request_id = $searchRequestId; text = "Show me two vehicles" } `
        | ConvertTo-Json -Compress
    $search = Invoke-RestMethod -Method Post $messagesUrl -ContentType "application/json" `
        -Body $searchBody
    if ($search.assistant_message.text -notmatch "^1\.") {
        throw "Search did not return a numbered grounded result."
    }

    $selectRequestId = [guid]::NewGuid().ToString()
    $selectText = "Select the first one"
    $selectBody = @{ request_id = $selectRequestId; text = $selectText } `
        | ConvertTo-Json -Compress
    $selection = Invoke-RestMethod -Method Post $messagesUrl -ContentType "application/json" `
        -Body $selectBody
    if (-not $selection.selected_vehicle_id) {
        throw "Selection was not persisted."
    }

    $safetyBody = @{ request_id = [guid]::NewGuid().ToString(); text = "both" } | ConvertTo-Json -Compress
    $safety = Invoke-RestMethod -Method Post $messagesUrl -ContentType "application/json" -Body $safetyBody
    if ($safety.assistant_message.text -notmatch "AA-1001" -or $safety.assistant_message.text -notmatch "NHTSA ID 202") {
        throw "Combined safety did not retain real imported vehicle and variant choices."
    }
    Invoke-Compose stop backend
    Invoke-Compose up --detach --force-recreate backend
    Wait-Healthy

    $replay = Invoke-RestMethod -Method Post $messagesUrl -ContentType "application/json" `
        -Body $selectBody
    if ($replay.assistant_message.id -ne $selection.assistant_message.id) {
        throw "Terminal transport retry did not replay the stored response."
    }

    $safetyReplay = Invoke-RestMethod -Method Post $messagesUrl -ContentType "application/json" -Body $safetyBody
    if ($safetyReplay.assistant_message.id -ne $safety.assistant_message.id) {
        throw "Safety replay did not preserve the committed reply."
    }
    $choiceBody = @{ request_id = [guid]::NewGuid().ToString(); text = "202" } | ConvertTo-Json -Compress
    $choice = Invoke-RestMethod -Method Post $messagesUrl -ContentType "application/json" -Body $choiceBody
    if ($choice.assistant_message.text -notmatch "Overall: 5/5") {
        throw "Variant choice did not survive recreation."
    }
    $detailBody = @{
        request_id = [guid]::NewGuid().ToString()
        text = "What is its price?"
    } | ConvertTo-Json -Compress
    $details = Invoke-RestMethod -Method Post $messagesUrl -ContentType "application/json" `
        -Body $detailBody
    if ($details.selected_vehicle_id -ne $selection.selected_vehicle_id) {
        throw "Selected vehicle context did not survive container recreation."
    }
    if ($details.assistant_message.text -notmatch "price:") {
        throw "Post-restart follow-up did not return grounded vehicle details."
    }

    Write-Host "Disposable container conversation acceptance passed."
} finally {
    Invoke-Compose down --volumes --remove-orphans
}
