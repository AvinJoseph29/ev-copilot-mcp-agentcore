import * as cdk from "aws-cdk-lib/core";
import { Construct } from "constructs";
import * as bedrockagentcore from "aws-cdk-lib/aws-bedrockagentcore";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as path from "path";
import { BaseStackProps } from "../types";

export interface GatewayStackProps extends BaseStackProps {
  /** AgentCore Runtime ID (from AgentCoreStack output) */
  runtimeId: string;
  /** AgentCore Runtime ARN (from AgentCoreStack output) */
  runtimeArn: string;
  /** Cognito User Pool ID (from AgentCoreStack) */
  cognitoUserPoolId: string;
  /** Cognito App Client ID (from AgentCoreStack) */
  cognitoClientId: string;
  /** Cognito token endpoint URL (from AgentCoreStack) */
  cognitoTokenEndpoint: string;
}

/**
 * AgentCore Gateway stack.
 *
 * Provisions:
 *  - AgentCore Gateway (MCP protocol, inbound CUSTOM_JWT authorizer —
 *    Cognito access tokens issued to the app client)
 *  - OAuth2 Credential Provider (Custom Resource)
 *  - Gateway Target (mcpServer) with OAUTH credential provider
 */
export class GatewayStack extends cdk.Stack {
  readonly gateway: bedrockagentcore.CfnGateway;
  readonly gatewayTarget: bedrockagentcore.CfnGatewayTarget;

  constructor(scope: Construct, id: string, props: GatewayStackProps) {
    super(scope, id, props);

    const region = cdk.Stack.of(this).region;
    const accountId = cdk.Stack.of(this).account;

    // =========================================================================
    // Gateway IAM Role
    // =========================================================================

    const gatewayRole = new iam.Role(this, "GatewayRole", {
      assumedBy: new iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
      description: `IAM role for ${props.appName} AgentCore Gateway`,
    });

    // Allow the Gateway to invoke the Runtime
    gatewayRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "InvokeRuntime",
        effect: iam.Effect.ALLOW,
        actions: [
          "bedrock-agentcore:InvokeRuntime",
          "bedrock-agentcore:InvokeAgentRuntime",
        ],
        resources: [props.runtimeArn, `${props.runtimeArn}/*`],
      }),
    );

    // Allow the Gateway to complete the full OAuth2 token exchange chain:
    // 1. GetWorkloadAccessToken — obtain a workload identity token
    // 2. GetResourceOauth2Token — exchange it for a Cognito JWT via the token vault
    // 3. secretsmanager:GetSecretValue — read the Cognito client secret
    gatewayRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "OAuthTokenExchange",
        effect: iam.Effect.ALLOW,
        actions: [
          "bedrock-agentcore:GetWorkloadAccessToken",
          "bedrock-agentcore:GetResourceOauth2Token",
        ],
        resources: [
          `arn:aws:bedrock-agentcore:${region}:${accountId}:workload-identity-directory/default`,
          `arn:aws:bedrock-agentcore:${region}:${accountId}:workload-identity-directory/default/*`,
          `arn:aws:bedrock-agentcore:${region}:${accountId}:token-vault/default`,
          `arn:aws:bedrock-agentcore:${region}:${accountId}:token-vault/default/*`,
          `arn:aws:bedrock-agentcore:${region}:${accountId}:token-vault/default/oauth2credentialprovider/*`,
        ],
      }),
    );

    // The OAuth2 credential provider stores the Cognito client secret in
    // Secrets Manager. The Gateway needs to read it during token exchange.
    gatewayRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "ReadOAuthSecret",
        effect: iam.Effect.ALLOW,
        actions: ["secretsmanager:GetSecretValue"],
        resources: [
          `arn:aws:secretsmanager:${region}:${accountId}:secret:*`,
        ],
      }),
    );

    // =========================================================================
    // OAuth2 Credential Provider (Custom Resource)
    // =========================================================================

    const oauthProviderFn = new lambda.Function(
      this,
      "OAuth2ProviderFunction",
      {
        runtime: lambda.Runtime.PYTHON_3_12,
        handler: "handler.lambda_handler",
        code: lambda.Code.fromAsset(
          path.join(__dirname, "../lambda/oauth2-provider"),
        ),
        timeout: cdk.Duration.seconds(60),
        memorySize: 256,
        description: `Manages ${props.appName} OAuth2 credential provider in AgentCore`,
      },
    );

    // Permissions for the custom resource Lambda
    oauthProviderFn.addToRolePolicy(
      new iam.PolicyStatement({
        sid: "CognitoDescribeClient",
        effect: iam.Effect.ALLOW,
        actions: ["cognito-idp:DescribeUserPoolClient"],
        resources: [
          `arn:aws:cognito-idp:${region}:${accountId}:userpool/${props.cognitoUserPoolId}`,
        ],
      }),
    );
    oauthProviderFn.addToRolePolicy(
      new iam.PolicyStatement({
        sid: "AgentCoreOAuth2Provider",
        effect: iam.Effect.ALLOW,
        actions: [
          "bedrock-agentcore:CreateOauth2CredentialProvider",
          "bedrock-agentcore:DeleteOauth2CredentialProvider",
          "bedrock-agentcore:GetOauth2CredentialProvider",
          "bedrock-agentcore:CreateTokenVault",
          "bedrock-agentcore:GetTokenVault",
          "secretsmanager:CreateSecret",
          "secretsmanager:DeleteSecret",
          "secretsmanager:PutSecretValue",
          "sso:*",
          "acps:*",
        ],
        resources: ["*"],
      }),
    );

    const providerName = `${props.appName}-cognito-oauth`;

    const oauthProvider = new cdk.CustomResource(
      this,
      "OAuth2CredentialProvider",
      {
        serviceToken: oauthProviderFn.functionArn,
        properties: {
          ProviderName: providerName,
          UserPoolId: props.cognitoUserPoolId,
          ClientId: props.cognitoClientId,
          Region: region,
        },
      },
    );

    const credentialProviderArn = oauthProvider.getAttString(
      "credentialProviderArn",
    );

    // =========================================================================
    // AgentCore Gateway
    // =========================================================================

    // Inbound auth: only Cognito access tokens issued to the app client
    // (client_credentials, the same client the agent already uses for the
    // direct Runtime connection) are accepted. Matches the Runtime's JWT
    // authorizer in AgentCoreStack.
    this.gateway = new bedrockagentcore.CfnGateway(this, "Gateway", {
      name: `${props.appName}-Gateway`,
      protocolType: "MCP",
      roleArn: gatewayRole.roleArn,
      authorizerType: "CUSTOM_JWT",
      authorizerConfiguration: {
        customJwtAuthorizer: {
          discoveryUrl: `https://cognito-idp.${region}.amazonaws.com/${props.cognitoUserPoolId}/.well-known/openid-configuration`,
          allowedClients: [props.cognitoClientId],
        },
      },
      description: `${props.appName} MCP Gateway — routes requests to the MCP server Runtime`,
    });

    // =========================================================================
    // Gateway Target — MCP Server (Runtime) with OAuth
    // =========================================================================

    // Construct the Runtime MCP endpoint URL.
    const encodedArn = cdk.Fn.join("", [
      "arn%3Aaws%3Abedrock-agentcore%3A",
      region,
      "%3A",
      accountId,
      "%3Aruntime%2F",
      props.runtimeId,
    ]);

    const runtimeEndpoint = cdk.Fn.join("", [
      "https://bedrock-agentcore.",
      region,
      ".amazonaws.com/runtimes/",
      encodedArn,
      "/invocations?qualifier=DEFAULT",
    ]);

    this.gatewayTarget = new bedrockagentcore.CfnGatewayTarget(
      this,
      "McpTarget",
      {
        name: `${props.appName}-McpTarget`,
        gatewayIdentifier: this.gateway.attrGatewayIdentifier,
        credentialProviderConfigurations: [
          {
            credentialProviderType: "OAUTH",
            credentialProvider: {
              oauthCredentialProvider: {
                providerArn: credentialProviderArn,
                scopes: [`${props.appName}-api/mcp`],
                grantType: "CLIENT_CREDENTIALS",
              },
            },
          },
        ],
        targetConfiguration: {
          mcp: {
            mcpServer: {
              endpoint: runtimeEndpoint,
            },
          },
        },
        description: "MCP server target pointing to the AgentCore Runtime",
      },
    );

    // Ensure correct creation ordering
    this.gatewayTarget.addDependency(this.gateway);
    this.gatewayTarget.node.addDependency(gatewayRole);
    this.gatewayTarget.node.addDependency(oauthProvider);

    // =========================================================================
    // Stack Outputs
    // =========================================================================

    new cdk.CfnOutput(this, "GatewayId", {
      value: this.gateway.attrGatewayIdentifier,
      description: "AgentCore Gateway ID",
      exportName: `${props.appName}-GatewayId`,
    });

    new cdk.CfnOutput(this, "GatewayArn", {
      value: this.gateway.attrGatewayArn,
      description: "AgentCore Gateway ARN",
      exportName: `${props.appName}-GatewayArn`,
    });

    new cdk.CfnOutput(this, "GatewayUrl", {
      value: this.gateway.attrGatewayUrl,
      description:
        "AgentCore Gateway URL — MCP clients connect to this endpoint",
      exportName: `${props.appName}-GatewayUrl`,
    });

    new cdk.CfnOutput(this, "GatewayTargetId", {
      value: this.gatewayTarget.attrTargetId,
      description: "Gateway Target ID",
      exportName: `${props.appName}-GatewayTargetId`,
    });

    new cdk.CfnOutput(this, "OAuth2ProviderArn", {
      value: credentialProviderArn,
      description: "OAuth2 Credential Provider ARN",
      exportName: `${props.appName}-OAuth2ProviderArn`,
    });
  }
}
