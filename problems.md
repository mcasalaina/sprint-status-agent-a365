# Known Problems & Troubleshooting

## Uploading Agentic App Manifest

### Problem: Graph API rejects agentic app uploads

When trying to upload the manifest zip via the Microsoft Graph API (`POST /appCatalogs/teamsApps`), both v1.0 and beta endpoints return:

```
400 BadRequest: "Agentic apps are not supported for uploading from Teams/Teams Admin Center. Please use M365 Admin Center."
```

This happens regardless of scope (`AppCatalog.Submit`, `AppCatalog.ReadWrite.All`).

**Root cause:** Microsoft explicitly blocks agentic app manifests (those containing `agenticUserTemplateManifest.json`) from being uploaded via the Teams Graph API. They must go through the M365 Admin Center UI.

**Workaround:** Upload manually via the M365 Admin Center:
1. Go to https://admin.cloud.microsoft → Agents → All agents
2. Look for "Upload custom agent" option
3. Upload `manifest/manifest.zip`

Or navigate directly to: `https://admin.cloud.microsoft/#/agents/uploadCustomAgent`

> **Note:** As of May 2026, there is no programmatic API for uploading agentic apps. This is a manual step.

### Problem: Manifest validation errors

The Teams manifest schema has strict limits:
- `name.short` — max **30 characters**
- `description.short` — max **80 characters**
- `name.short` and `description.short` cannot be identical

If your `agentBlueprintDisplayName` in `a365.config.json` exceeds 30 chars (e.g., "Sprint Status Intelligence Blueprint" = 36 chars), the manifest will need to be edited before packaging. The `a365 publish` command warns about this but doesn't auto-fix it.

**Fix:** Edit `manifest/manifest.json` after `a365 publish` generates it but before uploading:
```bash
# Check lengths
python3 -c "import json; d=json.load(open('manifest/manifest.json')); print(f'short: {len(d[\"name\"][\"short\"])} chars')"

# Edit, then rebuild zip
cd manifest && zip -j manifest.zip manifest.json agenticUserTemplateManifest.json color.png outline.png
```

## Duplicate Agents in Admin Portal

### Problem: Two "SprintStatusAgent" entries in admin.cloud.microsoft

When you delete a Foundry prompt agent and recreate it as a hosted agent (or vice versa), the old agent's Entra ID registration may persist in the A365 admin portal. Both show as "Platform: Microsoft Foundry" with different Entra agent IDs.

**Root cause:** Deleting a Foundry agent via the SDK (`client.agents.delete()`) removes it from Foundry but doesn't clean up the Entra ID app registration that Foundry auto-created.

**Workaround:** Manually stop/delete the stale entry from the admin portal (click the agent → Stop). Or delete the Entra app registration via:
```bash
az ad app delete --id <stale-entra-agent-id>
```

## AI Teammate Badge Not Showing

### Problem: Agent appears in admin portal but without "AI teammate" badge

The `a365 setup all` command creates the blueprint, but that alone doesn't make it an AI Teammate visible in Teams. You need **both**:

1. `a365 setup all --aiteammate` — creates the blueprint with AI Teammate configuration
2. `a365 publish --aiteammate` — generates the Teams manifest package
3. **Manual upload** of `manifest/manifest.zip` to M365 Admin Center

Without step 2+3, the blueprint exists in Entra ID but isn't registered as a Teams app, so it won't show the AI teammate badge or appear in Teams.

## Dependency Conflicts on Azure App Service (if using App Service instead of Foundry)

### Problem: `hyperlight-sandbox-backend-wasm` version conflict during Oryx build

When deploying to Azure App Service with Python 3.11, the `agent-framework-core[all]` transitive dependency pulls in `agent-framework-hyperlight` which requires `hyperlight-sandbox-backend-wasm>=0.4.0`. That package requires Python ≥3.13 on Linux, causing:

```
ERROR: Could not find a version that satisfies the requirement hyperlight-sandbox-backend-wasm==0.4.0
```

**Root cause:** `uv` on macOS resolves this fine (hyperlight is skipped on macOS), but `pip` on Linux App Service (Python 3.11) can't find a compatible wheel.

**Workaround:** Use `uv export` to generate a pinned requirements file, then remove hyperlight-related lines:
```bash
uv lock && uv export --format requirements-txt --no-hashes > requirements.txt
# Remove the "Resolved..." header line and "-e ." line
# Remove all hyperlight-related lines
grep -v -i hyperlight requirements.txt > requirements-clean.txt
mv requirements-clean.txt requirements.txt
```

Or better: use Foundry hosted agent deployment (Dockerfile-based) instead of App Service, which avoids this entirely since you control the Python version and build process.

## Hosted Agent Image Pull Fails Instantly (ImageError)

### Problem: Foundry cannot pull container image from ACR despite correct RBAC

All hosted agent versions fail instantly with:
```
ImageError: Failed to pull container image. Please check the image URI and ACR permissions, then retry. (image: <acr>.azurecr.io)
```

**What was verified:**
- Image exists and is linux/amd64 (built with `--platform linux/amd64`)
- ACR is Standard SKU, public access enabled, anonymous pull enabled, admin enabled
- All identities have `AcrPull` + `Container Registry Repository Reader`: per-agent identity, project managed identity, blueprint SP
- ACR is in same region (eastus2) as Foundry project
- Project connection to ACR created (`ContainerRegistry` category, `ManagedIdentity` auth)
- `useWorkspaceManagedIdentity` set to true
- Image is pullable via admin creds (200) and OAuth token exchange (200)
- Multiple fresh versions deployed — all fail instantly (within 5 seconds)

**Suspected root cause:** The Foundry project may not have hosted agents fully enabled, or there's a subscription-level flag missing. The `Foundry-Features: HostedAgents=V1Preview` header is required at the API level, suggesting this is still in gated preview and the subscription may not be enrolled.

**Workaround:** Use a **prompt agent** instead (which was proven working). The prompt agent uses the Foundry-managed infrastructure and doesn't need ACR/container setup.

## Foundry Hosted Agent Preview Header

### Problem: `preview_feature_required` error when creating hosted agent

Creating a hosted agent via the Python SDK (`client.agents.create_version()`) fails with:

```
Hosted agents is in preview. This operation requires the following opt-in preview feature(s):
HostedAgents=V1Preview. Include the 'Foundry-Features: HostedAgents=V1Preview' header.
```

**Root cause:** The `azure-ai-projects` SDK doesn't support injecting custom headers for preview features.

**Workaround:** Use the REST API directly with `requests`:
```python
import requests
from azure.identity import DefaultAzureCredential

token = DefaultAzureCredential().get_token("https://ai.azure.com/.default").token
url = f"{project_endpoint}/agents/{agent_name}/versions?api-version=2025-05-15-preview"

resp = requests.post(url, json={"definition": {...}}, headers={
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json",
    "Foundry-Features": "HostedAgents=V1Preview",
})
```
