import * as cdk from "aws-cdk-lib/core";
import { Construct } from "constructs";
import * as agentcore from "@aws-cdk/aws-bedrock-agentcore-alpha";
import * as iam from "aws-cdk-lib/aws-iam";
import * as logs from "aws-cdk-lib/aws-logs";
import * as bedrock from "aws-cdk-lib/aws-bedrock";
import { BaseStackProps } from "../types";

export interface AgentStackProps extends BaseStackProps {
  /** Full ECR image URI for the agent container */
  agentImageUri: string;
  /** Agent ECR repository ARN (from EcrStack) — for IAM pull permissions */
  agentEcrRepoArn: string;
  /** MCP Gateway URL (from GatewayStack) */
  mcpGatewayUrl: string;
  /** MCP Gateway ID (from GatewayStack) */
  mcpGatewayId: string;
  /** AgentCore Memory ID (from AgentCoreStack) */
  mcpMemoryId: string;
  /** Cognito App Client ID (from AgentCoreStack) */
  cognitoClientId: string;
  /** Secrets Manager ARN of the Cognito App Client secret (from AgentCoreStack) */
  cognitoClientSecretArn: string;
  /** Cognito token endpoint URL (from AgentCoreStack) */
  cognitoTokenEndpoint: string;
  /** MCP Runtime ID (from AgentCoreStack) — for direct mode */
  mcpRuntimeId: string;
  /** MCP Runtime ARN (from AgentCoreStack) — for direct mode */
  mcpRuntimeArn: string;
}

/**
 * Agent infrastructure stack.
 *
 * Provisions:
 *  - Bedrock Guardrail (content, topic, sensitive info, word policies)
 *  - AgentCore Runtime (HTTP protocol — agent, not MCP)
 *  - IAM permissions for Bedrock models, guardrails, memory, tracing,
 *    and reading the Cognito client secret from Secrets Manager
 *
 * Note: The agent ECR repository is in the EcrStack (deployed first so
 * images can be pushed before this stack creates the Runtime).
 */
export class AgentStack extends cdk.Stack {
  readonly agentRuntime: agentcore.Runtime;

  constructor(scope: Construct, id: string, props: AgentStackProps) {
    super(scope, id, props);

    const region = cdk.Stack.of(this).region;
    const accountId = cdk.Stack.of(this).account;

    // =========================================================================
    // Bedrock Guardrail — Content safety for agent I/O
    // =========================================================================

    const guardrail = new bedrock.CfnGuardrail(this, "AgentGuardrail", {
      name: `${props.appName}-agent-guardrail`,
      description:
        "Content safety guardrail for the EV Copilot agent. " +
        "Filters harmful content, blocks off-topic requests, and protects PII.",
      blockedInputMessaging:
        "I'm sorry, but I can't process that request. " +
        "I'm EV Copilot — please ask me about EV road trips, charging stops, battery range, or the weather for your drive!",
      blockedOutputsMessaging:
        "I apologize, but I'm unable to provide that response. " +
        "Let me help you plan your EV trip instead.",

      // Content policy — filter harmful content categories
      contentPolicyConfig: {
        filtersConfig: [
          {
            type: "HATE",
            inputStrength: "HIGH",
            outputStrength: "HIGH",
          },
          {
            type: "INSULTS",
            inputStrength: "HIGH",
            outputStrength: "HIGH",
          },
          {
            type: "SEXUAL",
            inputStrength: "HIGH",
            outputStrength: "HIGH",
          },
          {
            type: "VIOLENCE",
            inputStrength: "HIGH",
            outputStrength: "HIGH",
          },
          {
            type: "MISCONDUCT",
            inputStrength: "HIGH",
            outputStrength: "HIGH",
          },
          {
            type: "PROMPT_ATTACK",
            inputStrength: "HIGH",
            outputStrength: "NONE",
          },
        ],
      },

      // Topic policy — block off-topic conversations
      topicPolicyConfig: {
        topicsConfig: [
          {
            name: "vehicle-tampering",
            definition:
              "Requests to hack or tamper with vehicle software, disable safety systems, " +
              "bypass battery or charging limits, or make illegal vehicle modifications.",
            type: "DENY",
            examples: [
              "How do I disable the speed limiter on my EV?",
              "How can I jailbreak my Tesla to unlock features?",
              "How do I bypass the battery charge limit protection?",
            ],
          },
          {
            name: "professional-advice",
            definition:
              "Requests for personalised financial, investment, insurance, medical or legal advice, " +
              "such as loan decisions, stock picks, diagnoses or legal disputes.",
            type: "DENY",
            examples: [
              "Should I take a car loan or lease my EV?",
              "Which EV maker's stock should I buy?",
              "Can I sue the charging company for my accident?",
            ],
          },
          {
            name: "politics",
            definition:
              "Requests for opinions about political parties, politicians, elections, " +
              "or partisan political debates.",
            type: "DENY",
            examples: [
              "Which party should I vote for?",
              "What do you think of the prime minister?",
              "Is the opposition right about fuel taxes?",
            ],
          },
        ],
      },

      // Sensitive information policy — protect PII
      sensitiveInformationPolicyConfig: {
        piiEntitiesConfig: [
          { type: "EMAIL", action: "ANONYMIZE" },
          { type: "PHONE", action: "ANONYMIZE" },
          { type: "US_SOCIAL_SECURITY_NUMBER", action: "BLOCK" },
          { type: "CREDIT_DEBIT_CARD_NUMBER", action: "BLOCK" },
          { type: "CREDIT_DEBIT_CARD_CVV", action: "BLOCK" },
          { type: "CREDIT_DEBIT_CARD_EXPIRY", action: "BLOCK" },
          { type: "US_BANK_ACCOUNT_NUMBER", action: "BLOCK" },
          { type: "US_BANK_ROUTING_NUMBER", action: "BLOCK" },
          { type: "PIN", action: "BLOCK" },
          { type: "PASSWORD", action: "BLOCK" },
        ],
      },

      // Word policy — block profanity
      wordPolicyConfig: {
        managedWordListsConfig: [{ type: "PROFANITY" }],
      },
    });

    // Publish a numbered version for the guardrail
    const guardrailVersion = new bedrock.CfnGuardrailVersion(
      this,
      "AgentGuardrailV1",
      {
        guardrailIdentifier: guardrail.attrGuardrailId,
        description: "Initial CDK-deployed version.",
      },
    );

    // =========================================================================
    // AgentCore Runtime — HTTP protocol (agent, not MCP)
    // =========================================================================

    const artifact = agentcore.AgentRuntimeArtifact.fromImageUri(
      props.agentImageUri,
    );

    // Construct the MCP Runtime endpoint URL for direct mode
    const encodedMcpRuntimeArn = cdk.Fn.join("", [
      "arn%3Aaws%3Abedrock-agentcore%3A",
      region,
      "%3A",
      accountId,
      "%3Aruntime%2F",
      props.mcpRuntimeId,
    ]);
    const mcpRuntimeEndpoint = cdk.Fn.join("", [
      "https://bedrock-agentcore.",
      region,
      ".amazonaws.com/runtimes/",
      encodedMcpRuntimeArn,
      "/invocations?qualifier=DEFAULT",
    ]);

    this.agentRuntime = new agentcore.Runtime(this, "AgentRuntime", {
      runtimeName: `${props.appName}_agent`,
      agentRuntimeArtifact: artifact,
      description: `${props.appName} agent — LangGraph orchestrator with Router + ReAct + Reflection pattern`,
      protocolConfiguration: agentcore.ProtocolType.HTTP,
      networkConfiguration:
        agentcore.RuntimeNetworkConfiguration.usingPublicNetwork(),
      environmentVariables: {
        // App
        APP_NAME: props.appName,

        // AWS
        AWS_REGION: region,

        // Models (Bedrock Converse IDs / cross-region inference profiles)
        ORCHESTRATOR_MODEL_ID: "us.anthropic.claude-sonnet-4-6",
        ROUTER_MODEL_ID: "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        REFLECTION_MODEL_ID: "us.anthropic.claude-sonnet-4-6",

        // Gateway — tool proxy and invocation
        GATEWAY_URL: props.mcpGatewayUrl,
        GATEWAY_ID: props.mcpGatewayId,

        // Runtime — prompts and resources via direct MCP client
        RUNTIME_URL: mcpRuntimeEndpoint,
        RUNTIME_ID: props.mcpRuntimeId,
        COGNITO_CLIENT_ID: props.cognitoClientId,
        // Only the secret ARN — the agent reads the client secret from
        // Secrets Manager at startup (never a plaintext env var).
        COGNITO_CLIENT_SECRET_ARN: props.cognitoClientSecretArn,
        COGNITO_TOKEN_ENDPOINT: props.cognitoTokenEndpoint,

        // Memory
        MEMORY_ID: props.mcpMemoryId,

        // Guardrails (from this stack)
        BEDROCK_GUARDRAIL_ID: guardrail.attrGuardrailId,
        BEDROCK_GUARDRAIL_VERSION: guardrailVersion.attrVersion,
        GUARDRAIL_ENABLED: "true",

        // OpenTelemetry observability
        AGENT_OBSERVABILITY_ENABLED: "true",
        OTEL_SERVICE_NAME: `${props.appName}-agent`,
        OTEL_PYTHON_DISTRO: "aws_distro",
        OTEL_PYTHON_CONFIGURATOR: "aws_configurator",
        OTEL_EXPORTER_OTLP_PROTOCOL: "http/protobuf",
        OTEL_TRACES_EXPORTER: "otlp",
        OTEL_METRICS_EXPORTER: "otlp",
        OTEL_LOGS_EXPORTER: "otlp",
        OTEL_EXPORTER_OTLP_ENDPOINT: `https://xray.${region}.amazonaws.com`,
        OTEL_PROPAGATORS: "xray,tracecontext,baggage",
        OTEL_RESOURCE_ATTRIBUTES: [
          `service.name=${props.appName}-agent`,
          `aws.log.group.names=/aws/bedrock-agentcore/runtimes/${props.appName}-agent`,
          `cloud.region=${region}`,
        ].join(","),
        OTEL_EXPORTER_OTLP_LOGS_HEADERS: [
          `x-aws-log-group=/aws/bedrock-agentcore/runtimes/${props.appName}-agent`,
          "x-aws-log-stream=runtime-logs",
          "x-aws-metric-namespace=bedrock-agentcore",
        ].join(","),
      },
    });

    // -------------------------------------------------------------------------
    // IAM Permissions
    // -------------------------------------------------------------------------

    // ECR — pull agent container image (repo is in EcrStack)
    this.agentRuntime.addToRolePolicy(
      new iam.PolicyStatement({
        sid: "ECRPullImage",
        effect: iam.Effect.ALLOW,
        actions: [
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
        ],
        resources: [props.agentEcrRepoArn],
      }),
    );
    this.agentRuntime.addToRolePolicy(
      new iam.PolicyStatement({
        sid: "ECRAuth",
        effect: iam.Effect.ALLOW,
        actions: ["ecr:GetAuthorizationToken"],
        resources: ["*"],
      }),
    );

    // Bedrock — invoke foundation models and cross-region inference profiles.
    // The Converse / ConverseStream APIs (ChatBedrockConverse) are authorized
    // by bedrock:InvokeModel / bedrock:InvokeModelWithResponseStream.
    this.agentRuntime.addToRolePolicy(
      new iam.PolicyStatement({
        sid: "BedrockModelInvoke",
        effect: iam.Effect.ALLOW,
        actions: [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
        ],
        resources: [
          // Foundation models in any region (cross-region inference routes to us-west-2, us-east-1, etc.)
          `arn:aws:bedrock:*::foundation-model/*`,
          // Cross-region inference profiles (us.anthropic.* model IDs)
          `arn:aws:bedrock:${region}:${accountId}:inference-profile/*`,
          `arn:aws:bedrock:*:*:inference-profile/*`,
        ],
      }),
    );

    // Bedrock — apply guardrails
    this.agentRuntime.addToRolePolicy(
      new iam.PolicyStatement({
        sid: "BedrockGuardrailApply",
        effect: iam.Effect.ALLOW,
        actions: [
          "bedrock:ApplyGuardrail",
          "bedrock:GetGuardrail",
        ],
        resources: [
          guardrail.attrGuardrailArn,
          `${guardrail.attrGuardrailArn}/*`,
        ],
      }),
    );

    // Secrets Manager — read the Cognito client secret (direct Runtime auth)
    this.agentRuntime.addToRolePolicy(
      new iam.PolicyStatement({
        sid: "ReadCognitoClientSecret",
        effect: iam.Effect.ALLOW,
        actions: ["secretsmanager:GetSecretValue"],
        resources: [props.cognitoClientSecretArn],
      }),
    );

    // AgentCore Memory — read/write for conversation memory
    this.agentRuntime.addToRolePolicy(
      new iam.PolicyStatement({
        sid: "AgentCoreMemoryAccess",
        effect: iam.Effect.ALLOW,
        actions: ["bedrock-agentcore:*"],
        resources: [
          `arn:aws:bedrock-agentcore:${region}:${accountId}:memory/*`,
        ],
      }),
    );

    // AgentCore Gateway — invoke MCP tools via gateway
    this.agentRuntime.addToRolePolicy(
      new iam.PolicyStatement({
        sid: "AgentCoreGatewayInvoke",
        effect: iam.Effect.ALLOW,
        actions: [
          "bedrock-agentcore:InvokeGateway",
          "bedrock-agentcore:InvokeAgentRuntime",
          "bedrock-agentcore:InvokeRuntime",
        ],
        resources: [
          `arn:aws:bedrock-agentcore:${region}:${accountId}:gateway/*`,
          `arn:aws:bedrock-agentcore:${region}:${accountId}:runtime/*`,
        ],
      }),
    );

    // S3 Vector Store — used by memory for semantic search
    this.agentRuntime.addToRolePolicy(
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
    this.agentRuntime.addToRolePolicy(
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
    this.agentRuntime.addToRolePolicy(
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

    new logs.CfnResourcePolicy(this, "AgentXRayResourcePolicy", {
      policyName: `${props.appName}-agent-XRayCloudWatchLogsAccess`,
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

    new cdk.CfnOutput(this, "AgentRuntimeId", {
      value: this.agentRuntime.agentRuntimeId,
      description: "Agent Runtime ID",
      exportName: `${props.appName}-AgentRuntimeId`,
    });

    new cdk.CfnOutput(this, "AgentRuntimeArn", {
      value: this.agentRuntime.agentRuntimeArn,
      description: "Agent Runtime ARN",
      exportName: `${props.appName}-AgentRuntimeArn`,
    });

    new cdk.CfnOutput(this, "GuardrailId", {
      value: guardrail.attrGuardrailId,
      description: "Bedrock Guardrail ID for the agent",
      exportName: `${props.appName}-GuardrailId`,
    });

    new cdk.CfnOutput(this, "GuardrailVersion", {
      value: guardrailVersion.attrVersion,
      description: "Bedrock Guardrail Version",
      exportName: `${props.appName}-GuardrailVersion`,
    });

    new cdk.CfnOutput(this, "GuardrailArn", {
      value: guardrail.attrGuardrailArn,
      description: "Bedrock Guardrail ARN",
      exportName: `${props.appName}-GuardrailArn`,
    });
  }
}
