import * as cdk from "aws-cdk-lib/core";
import { Construct } from "constructs";
import * as agentcore from "@aws-cdk/aws-bedrock-agentcore-alpha";
import * as iam from "aws-cdk-lib/aws-iam";
import * as logs from "aws-cdk-lib/aws-logs";
import * as bedrock from "aws-cdk-lib/aws-bedrock";
import * as cognito from "aws-cdk-lib/aws-cognito";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import { BaseStackProps } from "../types";

export interface AgentCoreStackProps extends BaseStackProps {
  /** Full ECR image URI (e.g. 123456789012.dkr.ecr.us-east-2.amazonaws.com/evcopilot-mcp:latest) */
  imageUri: string;
}

/**
 * AgentCore infrastructure stack.
 *
 * Provisions:
 *  - Secrets Manager secrets for the Google Maps Platform and Open Charge Map API keys
 *  - AgentCore Runtime (container-based MCP server)
 *  - AgentCore Memory (user preference + semantic strategies)
 *  - Bedrock Prompts (agent scope, router, simple response, reflection)
 *  - Cognito (machine-to-machine JWT) + Secrets Manager secret for the client secret
 *  - X-Ray / CloudWatch observability
 */
export class AgentCoreStack extends cdk.Stack {
  readonly runtime: agentcore.Runtime;
  readonly memory: agentcore.Memory;
  readonly cognitoUserPoolId: string;
  readonly cognitoClientId: string;
  readonly cognitoClientSecretArn: string;
  readonly cognitoTokenEndpoint: string;

  constructor(scope: Construct, id: string, props: AgentCoreStackProps) {
    super(scope, id, props);

    const region = cdk.Stack.of(this).region;
    const accountId = cdk.Stack.of(this).account;

    // =========================================================================
    // Secrets
    // =========================================================================

    // Google Maps Platform key (Places, Routes, Geocoding, Elevation, Weather)
    // — update after deployment:
    //   aws secretsmanager put-secret-value --secret-id <appName>/google-maps-api-key \
    //     --secret-string '{"api_key":"your-key"}'
    const googleMapsApiSecret = new secretsmanager.Secret(
      this,
      "GoogleMapsApiSecret",
      {
        secretName: `${props.appName}/google-maps-api-key`,
        description:
          "Google Maps Platform API key for Places, Routes, Geocoding, Elevation & Weather APIs. Update after deployment.",
        secretObjectValue: {
          api_key: cdk.SecretValue.unsafePlainText(""),
        },
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      },
    );

    // Open Charge Map key (fallback charger coverage) — update after deployment:
    //   aws secretsmanager put-secret-value --secret-id <appName>/openchargemap-api-key \
    //     --secret-string '{"api_key":"your-key"}'
    const openChargeMapSecret = new secretsmanager.Secret(
      this,
      "OpenChargeMapSecret",
      {
        secretName: `${props.appName}/openchargemap-api-key`,
        description:
          "Open Charge Map API key for fallback charger search. Update after deployment.",
        secretObjectValue: {
          api_key: cdk.SecretValue.unsafePlainText(""),
        },
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      },
    );

    // =========================================================================
    // AgentCore Memory
    // =========================================================================

    this.memory = new agentcore.Memory(this, "Memory", {
      memoryName: `${props.appName}_memory`,
      description: `${props.appName} long-term memory with user preference and semantic strategies`,
      memoryStrategies: [
        agentcore.MemoryStrategy.usingUserPreference({
          name: "user_preference_strategy",
          namespaces: ["/preferences/{actorId}/"],
        }),
        agentcore.MemoryStrategy.usingSemantic({
          name: "semantic_strategy",
          namespaces: ["/facts/{actorId}/"],
        }),
      ],
    });

    // =========================================================================
    // Bedrock Prompt — Agent Scope Prompt
    // =========================================================================

    const agentScopePrompt = new bedrock.CfnPrompt(
      this,
      "AgentScopePrompt",
      {
        name: `${props.appName}-agent-scope-prompt`,
        description:
          "EV Copilot agent scope prompt — guides LLMs on how to orchestrate routing, charging, vehicle, weather, places and preference tools.",
        defaultVariant: "default",
        variants: [
          {
            name: "default",
            modelId: "anthropic.claude-sonnet-4-6",
            templateType: "TEXT",
            templateConfiguration: {
              text: {
                text: "Managed by application. See src/prompts/ for source of truth.",
              },
            },
            inferenceConfiguration: {
              text: {
                temperature: 0,
                topP: 1,
                maxTokens: 4096,
              },
            },
          },
        ],
      },
    );

    // Initial version — subsequent versions auto-managed by the Python app
    new bedrock.CfnPromptVersion(
      this,
      "AgentScopePromptV1",
      {
        promptArn: agentScopePrompt.attrArn,
        description:
          "Initial CDK-deployed version. Subsequent versions auto-managed by app.",
      },
    );

    // =========================================================================
    // Bedrock Prompt — Router Intent Classifier
    // =========================================================================

    const routerPrompt = new bedrock.CfnPrompt(this, "RouterPrompt", {
      name: `${props.appName}-router-prompt`,
      description:
        "Router intent classifier prompt — classifies user messages into trip_planning, simple, or off_topic.",
      defaultVariant: "default",
      variants: [
        {
          name: "default",
          modelId: "anthropic.claude-sonnet-4-6",
          templateType: "TEXT",
          templateConfiguration: {
            text: {
              text: "Managed by application. See src/prompts/ for source of truth.",
            },
          },
          inferenceConfiguration: {
            text: {
              temperature: 0,
              topP: 1,
              maxTokens: 256,
            },
          },
        },
      ],
    });

    new bedrock.CfnPromptVersion(this, "RouterPromptV1", {
      promptArn: routerPrompt.attrArn,
      description:
        "Initial CDK-deployed version. Subsequent versions auto-managed by app.",
    });

    // =========================================================================
    // Bedrock Prompt — Simple Response
    // =========================================================================

    const simpleResponsePrompt = new bedrock.CfnPrompt(
      this,
      "SimpleResponsePrompt",
      {
        name: `${props.appName}-simple-response-prompt`,
        description:
          "Simple response prompt — generates friendly responses for greetings, thanks, and off-topic messages.",
        defaultVariant: "default",
        variants: [
          {
            name: "default",
            modelId: "anthropic.claude-sonnet-4-6",
            templateType: "TEXT",
            templateConfiguration: {
              text: {
                text: "Managed by application. See src/prompts/ for source of truth.",
              },
            },
            inferenceConfiguration: {
              text: {
                temperature: 0.7,
                topP: 1,
                maxTokens: 1024,
              },
            },
          },
        ],
      },
    );

    new bedrock.CfnPromptVersion(this, "SimpleResponsePromptV1", {
      promptArn: simpleResponsePrompt.attrArn,
      description:
        "Initial CDK-deployed version. Subsequent versions auto-managed by app.",
    });

    // =========================================================================
    // Bedrock Prompt — Reflection Quality Review
    // =========================================================================

    const reflectionPrompt = new bedrock.CfnPrompt(
      this,
      "ReflectionPrompt",
      {
        name: `${props.appName}-reflection-prompt`,
        description:
          "Reflection quality review prompt — verifies the trip plan (simulation feasible, connectors compatible) after the ReAct loop.",
        defaultVariant: "default",
        variants: [
          {
            name: "default",
            modelId: "anthropic.claude-sonnet-4-6",
            templateType: "TEXT",
            templateConfiguration: {
              text: {
                text: "Managed by application. See src/prompts/ for source of truth.",
              },
            },
            inferenceConfiguration: {
              text: {
                temperature: 0,
                topP: 1,
                maxTokens: 512,
              },
            },
          },
        ],
      },
    );

    new bedrock.CfnPromptVersion(this, "ReflectionPromptV1", {
      promptArn: reflectionPrompt.attrArn,
      description:
        "Initial CDK-deployed version. Subsequent versions auto-managed by app.",
    });

    // =========================================================================
    // Cognito — JWT auth for Agent → Gateway, Agent → Runtime (direct) and Gateway → Runtime
    // =========================================================================

    const userPool = new cognito.UserPool(this, "UserPool", {
      userPoolName: `${props.appName}-pool`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const resourceServerScope = new cognito.ResourceServerScope({
      scopeName: "mcp",
      scopeDescription: `MCP access to ${props.appName}`,
    });

    const resourceServer = userPool.addResourceServer("ResourceServer", {
      identifier: `${props.appName}-api`,
      scopes: [resourceServerScope],
    });

    const appClient = new cognito.UserPoolClient(this, "AppClient", {
      userPool,
      generateSecret: true,
      oAuth: {
        flows: { clientCredentials: true },
        scopes: [
          cognito.OAuthScope.resourceServer(
            resourceServer,
            resourceServerScope,
          ),
        ],
      },
      supportedIdentityProviders: [
        cognito.UserPoolClientIdentityProvider.COGNITO,
      ],
    });

    const domain = userPool.addDomain("Domain", {
      cognitoDomain: {
        domainPrefix: `${props.appName.toLowerCase()}-${region}`,
      },
    });

    // Cognito client secret — stored in Secrets Manager so it never crosses
    // stacks as a plaintext CloudFormation export or runtime env var. The
    // agent receives only the secret ARN (COGNITO_CLIENT_SECRET_ARN) and
    // reads the raw client secret string at startup.
    const cognitoClientSecret = new secretsmanager.Secret(
      this,
      "CognitoClientSecret",
      {
        secretName: `${props.appName}/cognito-client-secret`,
        description:
          "Cognito App Client secret for direct Runtime access (plain string). Managed by CDK.",
        secretStringValue: appClient.userPoolClientSecret,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      },
    );

    this.cognitoUserPoolId = userPool.userPoolId;
    this.cognitoClientId = appClient.userPoolClientId;
    this.cognitoClientSecretArn = cognitoClientSecret.secretArn;
    this.cognitoTokenEndpoint = `${domain.baseUrl()}/oauth2/token`;

    // =========================================================================
    // AgentCore Runtime
    // =========================================================================

    const artifact = agentcore.AgentRuntimeArtifact.fromImageUri(
      props.imageUri,
    );

    this.runtime = new agentcore.Runtime(this, "Runtime", {
      runtimeName: `${props.appName}_mcp`,
      agentRuntimeArtifact: artifact,
      description: `${props.appName} MCP server (Charging, Places, Routing, Vehicle, Weather, User Preferences)`,
      protocolConfiguration: agentcore.ProtocolType.MCP,
      networkConfiguration:
        agentcore.RuntimeNetworkConfiguration.usingPublicNetwork(),
      authorizerConfiguration:
        agentcore.RuntimeAuthorizerConfiguration.usingCognito(
          userPool,
          [appClient],
        ),
      environmentVariables: {
        // AWS
        AWS_REGION: region,

        // AgentCore resources
        AGENTCORE_MEMORY_ID: this.memory.memoryId,
        BEDROCK_PROMPT_ID: agentScopePrompt.attrId,
        BEDROCK_PROMPT_ROUTER_ID: routerPrompt.attrId,
        BEDROCK_PROMPT_SIMPLE_ID: simpleResponsePrompt.attrId,
        BEDROCK_PROMPT_REFLECTION_ID: reflectionPrompt.attrId,

        // Secret ARNs — the application fetches the actual API keys from
        // Secrets Manager at startup.  This avoids the CloudFormation
        // dynamic-reference problem where resolved values are frozen at
        // stack creation time and never re-evaluated on updates.
        GOOGLE_MAPS_SECRET_ARN: googleMapsApiSecret.secretArn,
        OPEN_CHARGE_MAP_SECRET_ARN: openChargeMapSecret.secretArn,
        PROMPT_CACHE_TTL_SECONDS: "300",

        // OpenTelemetry observability
        AGENT_OBSERVABILITY_ENABLED: "true",
        OTEL_SERVICE_NAME: `${props.appName}-mcp`,
        OTEL_PYTHON_DISTRO: "aws_distro",
        OTEL_PYTHON_CONFIGURATOR: "aws_configurator",
        OTEL_EXPORTER_OTLP_PROTOCOL: "http/protobuf",
        OTEL_TRACES_EXPORTER: "otlp",
        OTEL_METRICS_EXPORTER: "otlp",
        OTEL_LOGS_EXPORTER: "otlp",
        OTEL_EXPORTER_OTLP_ENDPOINT: `https://xray.${region}.amazonaws.com`,
        OTEL_PROPAGATORS: "xray,tracecontext,baggage",
        OTEL_RESOURCE_ATTRIBUTES: [
          `service.name=${props.appName}-mcp`,
          `aws.log.group.names=/aws/bedrock-agentcore/runtimes/${props.appName}-mcp`,
          `cloud.region=${region}`,
        ].join(","),
        OTEL_EXPORTER_OTLP_LOGS_HEADERS: [
          `x-aws-log-group=/aws/bedrock-agentcore/runtimes/${props.appName}-mcp`,
          "x-aws-log-stream=runtime-logs",
          "x-aws-metric-namespace=bedrock-agentcore",
        ].join(","),
      },
    });

    // -------------------------------------------------------------------------
    // Additional IAM permissions for the runtime execution role
    // -------------------------------------------------------------------------

    // ECR — pull container image
    this.runtime.addToRolePolicy(
      new iam.PolicyStatement({
        sid: "ECRPullImage",
        effect: iam.Effect.ALLOW,
        actions: [
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
        ],
        resources: [
          `arn:aws:ecr:${region}:${accountId}:repository/${props.appName.toLowerCase()}-*`,
        ],
      }),
    );
    this.runtime.addToRolePolicy(
      new iam.PolicyStatement({
        sid: "ECRAuth",
        effect: iam.Effect.ALLOW,
        actions: ["ecr:GetAuthorizationToken"],
        resources: ["*"],
      }),
    );

    // Secrets Manager — read API keys at runtime
    googleMapsApiSecret.grantRead(this.runtime);
    openChargeMapSecret.grantRead(this.runtime);

    // AgentCore Memory — full access to memory resources
    this.runtime.addToRolePolicy(
      new iam.PolicyStatement({
        sid: "AgentCoreMemoryAccess",
        effect: iam.Effect.ALLOW,
        actions: ["bedrock-agentcore:*"],
        resources: [
          `arn:aws:bedrock-agentcore:${region}:${accountId}:memory/*`,
        ],
      }),
    );

    // Bedrock Prompt Management — full lifecycle (read, update, version, delete)
    this.runtime.addToRolePolicy(
      new iam.PolicyStatement({
        sid: "BedrockPromptManagement",
        effect: iam.Effect.ALLOW,
        actions: [
          "bedrock:GetPrompt",
          "bedrock:UpdatePrompt",
          "bedrock:CreatePromptVersion",
          "bedrock:ListPrompts",
          "bedrock:DeletePrompt",
        ],
        resources: [
          agentScopePrompt.attrArn,
          `${agentScopePrompt.attrArn}:*`,
          routerPrompt.attrArn,
          `${routerPrompt.attrArn}:*`,
          simpleResponsePrompt.attrArn,
          `${simpleResponsePrompt.attrArn}:*`,
          reflectionPrompt.attrArn,
          `${reflectionPrompt.attrArn}:*`,
        ],
      }),
    );

    // S3 Vector Store — used by memory for semantic search
    this.runtime.addToRolePolicy(
      new iam.PolicyStatement({
        sid: "S3VectorStoreAccess",
        effect: iam.Effect.ALLOW,
        actions: [
          "s3vectors:QueryVectors",
          "s3vectors:PutVectors",
          "s3vectors:GetVectors",
          "s3vectors:DeleteVectors",
        ],
        resources: [`arn:aws:s3vectors:${region}:${accountId}:bucket/*`],
      }),
    );

    // CloudWatch Logs delivery (OTLP)
    this.runtime.addToRolePolicy(
      new iam.PolicyStatement({
        sid: "OTLPCloudWatchExport",
        effect: iam.Effect.ALLOW,
        actions: [
          "logs:PutLogEvents",
          "logs:CreateLogStream",
          "logs:CreateLogGroup",
          "logs:DescribeLogStreams",
        ],
        resources: [
          `arn:aws:logs:${region}:${accountId}:log-group:/aws/vendedlogs/bedrock-agentcore/*`,
          `arn:aws:logs:${region}:${accountId}:log-group:/aws/vendedlogs/bedrock-agentcore/*:log-stream:*`,
          `arn:aws:logs:${region}:${accountId}:log-group:aws/spans:*`,
        ],
      }),
    );

    // CloudWatch Logs delivery API
    this.runtime.addToRolePolicy(
      new iam.PolicyStatement({
        sid: "CloudWatchLogsDelivery",
        effect: iam.Effect.ALLOW,
        actions: [
          "logs:PutDeliverySource",
          "logs:PutDeliveryDestination",
          "logs:CreateDelivery",
          "logs:GetDeliverySource",
          "logs:GetDeliveryDestination",
          "logs:GetDelivery",
          "logs:DeleteDeliverySource",
          "logs:DeleteDeliveryDestination",
          "logs:DeleteDelivery",
        ],
        resources: ["*"],
      }),
    );

    // =========================================================================
    // Observability — X-Ray → CloudWatch Logs resource policy
    // =========================================================================

    new logs.CfnResourcePolicy(this, "XRayResourcePolicy", {
      policyName: `${props.appName}-XRayCloudWatchLogsAccess`,
      policyDocument: JSON.stringify({
        Version: "2012-10-17",
        Statement: [
          {
            Effect: "Allow",
            Principal: { Service: "xray.amazonaws.com" },
            Action: ["logs:PutLogEvents", "logs:CreateLogStream"],
            Resource: `arn:aws:logs:${region}:${accountId}:log-group:aws/spans:*`,
          },
        ],
      }),
    });

    // =========================================================================
    // Stack Outputs
    // =========================================================================

    new cdk.CfnOutput(this, "RuntimeId", {
      value: this.runtime.agentRuntimeId,
      description: "AgentCore Runtime ID",
      exportName: `${props.appName}-RuntimeId`,
    });

    new cdk.CfnOutput(this, "RuntimeArn", {
      value: this.runtime.agentRuntimeArn,
      description: "AgentCore Runtime ARN",
      exportName: `${props.appName}-RuntimeArn`,
    });

    new cdk.CfnOutput(this, "MemoryId", {
      value: this.memory.memoryId,
      description: "AgentCore Memory ID",
      exportName: `${props.appName}-MemoryId`,
    });

    new cdk.CfnOutput(this, "MemoryArn", {
      value: this.memory.memoryArn,
      description: "AgentCore Memory ARN",
      exportName: `${props.appName}-MemoryArn`,
    });

    new cdk.CfnOutput(this, "GoogleApiSecretArn", {
      value: googleMapsApiSecret.secretArn,
      description: "Google Maps Platform API key secret ARN",
      exportName: `${props.appName}-GoogleApiSecretArn`,
    });

    new cdk.CfnOutput(this, "OpenChargeMapSecretArn", {
      value: openChargeMapSecret.secretArn,
      description: "Open Charge Map API key secret ARN",
      exportName: `${props.appName}-OpenChargeMapSecretArn`,
    });

    new cdk.CfnOutput(this, "CognitoClientSecretArn", {
      value: cognitoClientSecret.secretArn,
      description: "Cognito App Client secret ARN (Secrets Manager)",
      exportName: `${props.appName}-CognitoClientSecretArn`,
    });

    new cdk.CfnOutput(this, "AgentScopePromptId", {
      value: agentScopePrompt.attrId,
      description: "Bedrock Prompt ID for the agent scope prompt",
      exportName: `${props.appName}-AgentScopePromptId`,
    });

    new cdk.CfnOutput(this, "AgentScopePromptArn", {
      value: agentScopePrompt.attrArn,
      description: "Bedrock Prompt ARN for the agent scope prompt",
      exportName: `${props.appName}-AgentScopePromptArn`,
    });

    new cdk.CfnOutput(this, "RouterPromptId", {
      value: routerPrompt.attrId,
      description: "Bedrock Prompt ID for the router intent classifier prompt",
      exportName: `${props.appName}-RouterPromptId`,
    });

    new cdk.CfnOutput(this, "RouterPromptArn", {
      value: routerPrompt.attrArn,
      description: "Bedrock Prompt ARN for the router intent classifier prompt",
      exportName: `${props.appName}-RouterPromptArn`,
    });

    new cdk.CfnOutput(this, "SimpleResponsePromptId", {
      value: simpleResponsePrompt.attrId,
      description: "Bedrock Prompt ID for the simple response prompt",
      exportName: `${props.appName}-SimpleResponsePromptId`,
    });

    new cdk.CfnOutput(this, "SimpleResponsePromptArn", {
      value: simpleResponsePrompt.attrArn,
      description: "Bedrock Prompt ARN for the simple response prompt",
      exportName: `${props.appName}-SimpleResponsePromptArn`,
    });

    new cdk.CfnOutput(this, "ReflectionPromptId", {
      value: reflectionPrompt.attrId,
      description: "Bedrock Prompt ID for the reflection quality review prompt",
      exportName: `${props.appName}-ReflectionPromptId`,
    });

    new cdk.CfnOutput(this, "ReflectionPromptArn", {
      value: reflectionPrompt.attrArn,
      description: "Bedrock Prompt ARN for the reflection quality review prompt",
      exportName: `${props.appName}-ReflectionPromptArn`,
    });

    new cdk.CfnOutput(this, "CognitoUserPoolId", {
      value: userPool.userPoolId,
      description: "Cognito User Pool ID (for Gateway OAuth)",
      exportName: `${props.appName}-CognitoUserPoolId`,
    });

    new cdk.CfnOutput(this, "CognitoClientId", {
      value: appClient.userPoolClientId,
      description: "Cognito App Client ID (for Gateway OAuth)",
      exportName: `${props.appName}-CognitoClientId`,
    });

    new cdk.CfnOutput(this, "CognitoTokenEndpoint", {
      value: this.cognitoTokenEndpoint,
      description: "Cognito token endpoint URL",
      exportName: `${props.appName}-CognitoTokenEndpoint`,
    });
  }
}
