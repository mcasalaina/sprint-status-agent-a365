# Copyright (c) Microsoft. All rights reserved.

"""
Sprint Status Intelligence Agent — Foundry Hosted Agent

Uses the Microsoft Agent Framework with ResponsesHostServer to expose
the agent via Foundry's /responses protocol. WorkIQ (Mail) is connected
as an MCP tool for M365 data access.
"""

import logging
import os

from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from dotenv import load_dotenv

load_dotenv(override=False)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _load_instructions() -> str:
    """Load agent instructions from file or environment."""
    instructions_file = os.getenv("AGENT_INSTRUCTIONS_FILE", "instructions.txt")
    if os.path.exists(instructions_file):
        with open(instructions_file) as f:
            return f.read()
    return os.getenv("AGENT_INSTRUCTIONS", "You are a sprint status intelligence agent.")


def main():
    project_endpoint = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
    model = os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"]

    # Use ManagedIdentityCredential in production, DefaultAzureCredential for local dev
    if os.getenv("WEBSITE_INSTANCE_ID") or os.getenv("RUNNING_IN_PRODUCTION"):
        credential = ManagedIdentityCredential()
    else:
        credential = DefaultAzureCredential()

    client = FoundryChatClient(
        project_endpoint=project_endpoint,
        model=model,
        credential=credential,
    )

    # WorkIQ Mail MCP tool — same server the prompt agent used
    workiq_mail_url = os.getenv(
        "WORKIQ_MAIL_URL",
        "https://agent365.svc.cloud.microsoft/agents/servers/mcp_MailTools",
    )
    workiq_connection_id = os.getenv("WORKIQ_CONNECTION_ID", "WorkIQMail")

    tools = []
    tools.append(client.get_mcp_tool(
        name="WorkIQMail",
        url=workiq_mail_url,
        approval_mode="never_require",
        project_connection_id=workiq_connection_id,
    ))

    logger.info(f"Registered WorkIQ Mail MCP tool: {workiq_mail_url}")

    instructions = _load_instructions()
    logger.info(f"Loaded instructions ({len(instructions)} chars)")

    agent = Agent(
        client=client,
        instructions=instructions,
        tools=tools,
        default_options={"store": False},
    )

    logger.info(
        f"Starting Sprint Status Intelligence Agent "
        f"(model={model}, endpoint={project_endpoint})"
    )

    server = ResponsesHostServer(agent)
    server.run()


if __name__ == "__main__":
    main()
