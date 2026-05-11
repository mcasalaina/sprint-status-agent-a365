# Sprint Status Intelligence Agent

A Foundry-hosted agent that mines M365 data via WorkIQ to provide engineering sprint status reports. Built as an **AI Teammate** on Agent 365, accessible through Microsoft Teams.

## Architecture

```
Teams User (dev lead / PM)
    ↕  (Agent 365 / Teams)
AI Teammate Blueprint  (a365 setup --aiteammate)
    ↕
Foundry Hosted Agent  (main.py → ResponsesHostServer on port 8088)
    │   Uses Agent Framework + FoundryChatClient
    ↕  (MCP tool — WorkIQ Mail)
M365 Data  (Outlook, Calendar, OneDrive/SharePoint, Teams)
```

### Key Components

| Component | What it is | Where it lives |
|-----------|-----------|---------------|
| **Foundry Hosted Agent** | Container running `main.py` with `ResponsesHostServer` | Azure AI Foundry (container image in ACR) |
| **A365 Blueprint** | AI Teammate registration for Teams integration | Entra ID + Agent 365 admin |
| **WorkIQ Mail** | MCP tool for searching/sending M365 email | Connected via `FoundryChatClient.get_mcp_tool()` |
| **Instructions** | Agent system prompt with team roster, search patterns, response format | `instructions.txt` (loaded at runtime) |

## Setup Guide (Reproducing This Pattern)

### Prerequisites

- Azure subscription with Azure AI Foundry project
- Azure Container Registry (ACR)
- `az` CLI, `a365` CLI (`dotnet tool install -g Microsoft.Agents.A365.DevTools.Cli`)
- Python 3.11+, `uv` (recommended) or `pip`
- Tenant enrolled in [Frontier Preview Program](https://adoption.microsoft.com/copilot/frontier-program/)

### Step 1: Create the Foundry Project

You need a Foundry project with a model deployment (e.g., `gpt-4.1-mini-1`). Note your:
- **Project endpoint**: `https://<resource>.services.ai.azure.com/api/projects/<project>`
- **Model deployment name**: e.g., `gpt-4.1-mini-1`
- **WorkIQ Mail connection ID**: e.g., `WorkIQMail` (configured in Foundry project connections)

### Step 2: Write Agent Code

The hosted agent uses the **Microsoft Agent Framework** with the `responses` protocol:

```python
from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import ResponsesHostServer

client = FoundryChatClient(project_endpoint=..., model=..., credential=...)
agent = Agent(client=client, instructions=..., tools=[...])
server = ResponsesHostServer(agent)
server.run()  # Starts HTTP server on port 8088
```

Key files:
- `main.py` — Agent entry point (loads instructions, wires MCP tools, starts server)
- `instructions.txt` — System prompt (team roster, search patterns, response format)
- `agent.yaml` — Foundry hosted agent definition (protocol, resources, env vars)
- `Dockerfile` — Container image (Python 3.12-slim, port 8088)
- `requirements.txt` — Dependencies (`agent-framework`, `agent-framework-foundry-hosting`)

### Step 3: Build and Push Container Image

Build the image using ACR Tasks (no local Docker needed):

```bash
# Create a clean build context (exclude .venv, .git, etc.)
mkdir -p /tmp/agent-build
cp main.py instructions.txt requirements.txt agent.yaml Dockerfile .dockerignore /tmp/agent-build/

# Build in ACR
TIMESTAMP=$(date +%Y%m%d%H%M)
az acr build \
  --registry <acr-name> \
  --image <agent-name>:<timestamp> \
  --platform linux/amd64 \
  --file Dockerfile \
  /tmp/agent-build/
```

> **Important:** Always use `--platform linux/amd64`. Use a timestamp tag (not `latest`) for uniqueness.

### Step 4: Deploy as Foundry Hosted Agent

Create the hosted agent via the Foundry REST API (SDK doesn't support preview features yet):

```python
import requests
from azure.identity import DefaultAzureCredential

token = DefaultAzureCredential().get_token("https://ai.azure.com/.default").token
url = f"{project_endpoint}/agents/{agent_name}/versions?api-version=2025-05-15-preview"

resp = requests.post(url, json={
    "definition": {
        "kind": "hosted",
        "image": "<acr>.azurecr.io/<repo>:<tag>",
        "cpu": "0.25",
        "memory": "0.5Gi",
        "container_protocol_versions": [
            {"protocol": "responses", "version": "1.0.0"}
        ],
        "environment_variables": {
            "AZURE_AI_MODEL_DEPLOYMENT_NAME": "<model>",
            # ... other env vars
        }
    },
    "description": "...",
}, headers={
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json",
    "Foundry-Features": "HostedAgents=V1Preview",  # Required while in preview
})
```

### Step 5: Assign RBAC

The per-agent identity (from the create response) needs:

```bash
# Azure AI User on the Cognitive Services account
az role assignment create \
  --role "Azure AI User" \
  --assignee-object-id <agent-principal-id> \
  --assignee-principal-type ServicePrincipal \
  --scope <cognitive-services-resource-id>

# ACR Pull on the container registry
az role assignment create \
  --role "AcrPull" \
  --assignee-object-id <agent-principal-id> \
  --assignee-principal-type ServicePrincipal \
  --scope <acr-resource-id>
```

### Step 6: Register as AI Teammate (A365 Blueprint)

This is what makes the agent appear in Teams with the "AI teammate" badge.

#### 6a: Configure `a365.config.json`

```json
{
  "tenantId": "<your-tenant-id>",
  "subscriptionId": "<your-subscription-id>",
  "resourceGroup": "<your-rg>",
  "location": "eastus",
  "environment": "prod",
  "needDeployment": true,
  "graphBaseUrl": "https://graph.microsoft.com",
  "clientAppId": "<a365-cli-app-id>",
  "appServicePlanName": "<rg>-plan",
  "appServicePlanSku": "B1",
  "webAppName": "<webapp-name>",
  "agentIdentityDisplayName": "<Agent Name> Identity",
  "agentBlueprintDisplayName": "<Agent Name> Blueprint",
  "agentUserPrincipalName": "<agentname>@<tenant>.onmicrosoft.com",
  "agentUserDisplayName": "<Agent Name> Agent User",
  "managerEmail": "<manager>@<tenant>.onmicrosoft.com",
  "agentUserUsageLocation": "US",
  "deploymentProjectPath": "<path-to-repo>",
  "agentDescription": "<Agent Name> — Agent 365 Agent",
  "messagingEndpoint": "https://<webapp-name>.azurewebsites.net/api/messages",
  "customBlueprintPermissions": [
    {
      "resourceAppId": "ea9ffc3e-8a23-4a7d-836d-234d7c7565c1",
      "resourceName": "Agent 365 Tools",
      "scopes": ["McpServers.Mail.All", "McpServers.Teams.All", "McpServersMetadata.Read.All"]
    },
    {
      "resourceAppId": "7d312290-28c8-473c-a0ed-8e53749b6d6d",
      "resourceName": "Microsoft Cognitive Services",
      "scopes": ["user_impersonation"]
    },
    {
      "resourceAppId": "18a66f5f-dbdf-4c17-9dd7-1634712a9cbe",
      "resourceName": "Azure Machine Learning Services",
      "scopes": ["user_impersonation"]
    }
  ]
}
```

Key naming conventions:
- `agentBlueprintDisplayName` **must** end with "Blueprint" (e.g., "Sprint Status Intelligence Blueprint")
- `agentUserPrincipalName` must be a valid UPN in your tenant

#### 6b: Run `a365 setup all --aiteammate`

```bash
~/.dotnet/tools/a365 setup all --aiteammate --verbose
```

> **Critical:** The `--aiteammate` flag is what makes it register as an AI Teammate in Teams. Without it, you get a blueprint-only agent that won't show the AI teammate badge or appear properly in Teams.

This command:
1. Validates prerequisites (Azure auth, PowerShell modules, client app)
2. Creates the Entra ID blueprint application
3. Configures inheritable permissions (Mail, Teams, Cognitive Services)
4. Grants admin consent and S2S app roles
5. Registers the messaging endpoint
6. Stamps credentials into your `.env` file

#### 6c: Publish the manifest

The `a365 setup all` creates the blueprint, but you need to **publish** to make it visible as an AI Teammate:

```bash
~/.dotnet/tools/a365 publish --aiteammate -v
```

This generates a `manifest/manifest.zip`. Before packaging, the CLI will prompt you to edit the manifest — fix:
- `name.short` — must be ≤30 chars (e.g., "Sprint Status Blueprint")
- `description.short` / `description.full` — meaningful descriptions

Then **manually upload** the zip to the M365 Admin Center:
1. Go to **https://admin.microsoft.com** → **Agents** → **All agents** → **Upload custom agent**
2. Upload `manifest/manifest.zip`

> **Important:** This upload step is required. Without it, the agent won't show up with the AI teammate badge in Teams.

#### 6d: Verify in Admin Portal

After setup, your agent should appear at:
```
https://admin.cloud.microsoft/settings/copilot/agents
```

It should show:
- Name: `<Agent Name> Blueprint`
- Badge: **AI teammate**
- Channel: Teams icon
- Publisher type: Your org

### Step 7: Clean Up / Redo

If you need to start over:

```bash
# Delete the blueprint (Entra app + registrations)
~/.dotnet/tools/a365 cleanup blueprint -v

# Then re-run setup
~/.dotnet/tools/a365 setup all --aiteammate --verbose
```

## Local Development

```bash
# Create venv and install deps
uv venv --python 3.13 .venv
uv pip install -r requirements.txt

# Create .env from template
cp .env.template .env
# Fill in FOUNDRY_PROJECT_ENDPOINT, AZURE_AI_MODEL_DEPLOYMENT_NAME, etc.

# Run locally (agent serves on port 8088)
.venv/bin/python main.py
```

## Project Structure

```
├── main.py                          # Foundry hosted agent entry point
├── instructions.txt                 # Agent system prompt (loaded at runtime)
├── agent.yaml                       # Foundry hosted agent definition
├── Dockerfile                       # Container image for ACR/Foundry
├── requirements.txt                 # Python dependencies
├── .env.template                    # Environment variable template
├── a365.config.json                 # A365 blueprint configuration
├── sprint-agent-instructions.md     # Instructions source (markdown wrapper)
├── host_agent_server.py             # A365 host server (legacy scaffolding)
├── sprint_agent.py                  # A365 agent class (legacy scaffolding)
├── agent_interface.py               # Abstract agent base class
├── start_with_generic_host.py       # A365 entry point (legacy scaffolding)
├── local_authentication_options.py  # Local auth helper
├── token_cache.py                   # Token cache utility
└── pyproject.toml                   # Project metadata
```

> **Note:** The `host_agent_server.py`, `sprint_agent.py`, and related A365 scaffolding files are from an earlier architecture iteration. The active deployment uses `main.py` with `ResponsesHostServer`.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `FOUNDRY_PROJECT_ENDPOINT` | Yes | Foundry project endpoint URL |
| `AZURE_AI_MODEL_DEPLOYMENT_NAME` | Yes | Model deployment name (e.g., `gpt-4.1-mini-1`) |
| `WORKIQ_MAIL_URL` | No | WorkIQ Mail MCP server URL (has default) |
| `WORKIQ_CONNECTION_ID` | No | WorkIQ project connection ID (default: `WorkIQMail`) |
| `AGENT_INSTRUCTIONS_FILE` | No | Path to instructions file (default: `instructions.txt`) |
