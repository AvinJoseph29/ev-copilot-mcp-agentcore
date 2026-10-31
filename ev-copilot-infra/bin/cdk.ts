#!/usr/bin/env node
import * as cdk from "aws-cdk-lib";
import { BaseStackProps } from "../lib/types";
import {
  EcrStack,
  AgentCoreStack,
  GatewayStack,
  AgentStack,
  UiStack,
} from "../lib/stacks";

const app = new cdk.App();

// Override image URIs via context:
//   npx cdk deploy --all -c imageUri=<account>.dkr.ecr.<region>.amazonaws.com/evcopilot-mcp:<tag>
//   npx cdk deploy --all -c agentImageUri=<account>.dkr.ecr.<region>.amazonaws.com/evcopilot-agent:<tag>
//   npx cdk deploy --all -c uiImageUri=<account>.dkr.ecr.<region>.amazonaws.com/evcopilot-ui:<tag>
// Optional Google Maps Map ID for the UI (defaults to DEMO_MAP_ID):
//   npx cdk deploy --all -c mapsMapId=<your-map-id>
const existingImageUri = app.node.tryGetContext("imageUri") as
  | string
  | undefined;
const existingAgentImageUri = app.node.tryGetContext("agentImageUri") as
  | string
  | undefined;
const existingUiImageUri = app.node.tryGetContext("uiImageUri") as
  | string
  | undefined;
const existingMapsMapId = app.node.tryGetContext("mapsMapId") as
  | string
  | undefined;

const appName = "evCopilot";
const ecrRepoName = `${appName.toLowerCase()}-mcp`;
const agentEcrRepoName = `${appName.toLowerCase()}-agent`;
const uiEcrRepoName = `${appName.toLowerCase()}-ui`;

const deploymentProps: BaseStackProps = {
  appName,
  env: { account: process.env.CDK_DEFAULT_ACCOUNT, region: process.env.CDK_DEFAULT_REGION },
};

// ECR repositories — always created first as infrastructure
const ecrStack = new EcrStack(app, `${appName}-EcrStack`, deploymentProps);

// Build default image URIs from account/region tokens (no cross-stack reference)
const defaultImageUri = `${cdk.Aws.ACCOUNT_ID}.dkr.ecr.${cdk.Aws.REGION}.amazonaws.com/${ecrRepoName}:latest`;
const imageUri = existingImageUri || defaultImageUri;

const defaultAgentImageUri = `${cdk.Aws.ACCOUNT_ID}.dkr.ecr.${cdk.Aws.REGION}.amazonaws.com/${agentEcrRepoName}:latest`;
const agentImageUri = existingAgentImageUri || defaultAgentImageUri;

const defaultUiImageUri = `${cdk.Aws.ACCOUNT_ID}.dkr.ecr.${cdk.Aws.REGION}.amazonaws.com/${uiEcrRepoName}:latest`;
const uiImageUri = existingUiImageUri || defaultUiImageUri;

// Google Maps Map ID (vector map styling / Advanced Markers) — DEMO_MAP_ID works for development
const mapsMapId = existingMapsMapId || "DEMO_MAP_ID";

if (existingImageUri) {
  console.log(`Using provided MCP image URI: ${existingImageUri}`);
} else {
  console.log(`Using default MCP ECR image URI: ${ecrRepoName}:latest`);
}

if (existingAgentImageUri) {
  console.log(`Using provided agent image URI: ${existingAgentImageUri}`);
} else {
  console.log(`Using default agent ECR image URI: ${agentEcrRepoName}:latest`);
}

if (existingUiImageUri) {
  console.log(`Using provided UI image URI: ${existingUiImageUri}`);
} else {
  console.log(`Using default UI ECR image URI: ${uiEcrRepoName}:latest`);
}

// AgentCore stack — Runtime, Memory, Prompts, Cognito, Secrets, Observability
const agentCoreStack = new AgentCoreStack(app, `${appName}-AgentCoreStack`, {
  ...deploymentProps,
  imageUri,
});

// Gateway stack — MCP Gateway exposing the Runtime
const gatewayStack = new GatewayStack(app, `${appName}-GatewayStack`, {
  ...deploymentProps,
  runtimeId: agentCoreStack.runtime.agentRuntimeId,
  runtimeArn: agentCoreStack.runtime.agentRuntimeArn,
  cognitoUserPoolId: agentCoreStack.cognitoUserPoolId,
  cognitoClientId: agentCoreStack.cognitoClientId,
  cognitoTokenEndpoint: agentCoreStack.cognitoTokenEndpoint,
});

// Agent stack — LangGraph agent consuming MCP tools via Gateway/Runtime
const agentStack = new AgentStack(app, `${appName}-AgentStack`, {
  ...deploymentProps,
  agentImageUri,
  agentEcrRepoArn: ecrStack.agentRepository.repositoryArn,
  mcpGatewayUrl: gatewayStack.gateway.attrGatewayUrl,
  mcpGatewayId: gatewayStack.gateway.attrGatewayIdentifier,
  mcpMemoryId: agentCoreStack.memory.memoryId,
  cognitoClientId: agentCoreStack.cognitoClientId,
  cognitoClientSecretArn: agentCoreStack.cognitoClientSecretArn,
  cognitoTokenEndpoint: agentCoreStack.cognitoTokenEndpoint,
  mcpRuntimeId: agentCoreStack.runtime.agentRuntimeId,
  mcpRuntimeArn: agentCoreStack.runtime.agentRuntimeArn,
});

// UI stack — Next.js web UI on App Runner, connected to the Agent Runtime
new UiStack(app, `${appName}-UiStack`, {
  ...deploymentProps,
  uiImageUri,
  uiEcrRepoArn: ecrStack.uiRepository.repositoryArn,
  agentRuntimeArn: agentStack.agentRuntime.agentRuntimeArn,
  mapsMapId,
});
