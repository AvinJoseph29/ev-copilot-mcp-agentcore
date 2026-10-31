import * as cdk from "aws-cdk-lib/core";
import { Construct } from "constructs";
import * as iam from "aws-cdk-lib/aws-iam";
import * as apprunner from "aws-cdk-lib/aws-apprunner";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import { BaseStackProps } from "../types";

export interface UiStackProps extends BaseStackProps {
  /** Full ECR image URI for the UI container */
  uiImageUri: string;
  /** UI ECR repository ARN (from EcrStack) — for IAM pull permissions */
  uiEcrRepoArn: string;
  /** Agent Runtime ARN (from AgentStack) — passed to the UI as env var */
  agentRuntimeArn: string;
  /** Google Maps Map ID for the browser map (context `mapsMapId`, default DEMO_MAP_ID) */
  mapsMapId: string;
}

/**
 * UI infrastructure stack.
 *
 * Provisions:
 *  - Secrets Manager secret for the Google Maps browser (Maps JavaScript API) key
 *  - AWS App Runner service running the Next.js UI container
 *  - IAM access role for ECR image pull
 *  - IAM instance role for AgentCore Runtime invocation and reading the
 *    browser key secret
 */
export class UiStack extends cdk.Stack {
  /** The public App Runner service URL */
  readonly serviceUrl: string;

  constructor(scope: Construct, id: string, props: UiStackProps) {
    super(scope, id, props);

    const region = cdk.Stack.of(this).region;
    const accountId = cdk.Stack.of(this).account;

    // =========================================================================
    // Secrets — Google Maps browser key (plain string, NOT JSON)
    // =========================================================================

    // Maps JavaScript API key used by the browser map. It is visible to end
    // users, so restrict it by HTTP referrer (the App Runner URL) in the
    // Google Cloud console. Secrets Manager rejects an empty value and App
    // Runner needs a current version at service creation, so the secret is
    // seeded with the placeholder "REPLACE_ME" — update after deployment:
    //   aws secretsmanager put-secret-value --secret-id <appName>/google-maps-browser-key \
    //     --secret-string 'your-browser-key'
    //   aws apprunner start-deployment --service-arn <UiServiceArn>
    const mapsBrowserKeySecret = new secretsmanager.Secret(
      this,
      "GoogleMapsBrowserKeySecret",
      {
        secretName: `${props.appName}/google-maps-browser-key`,
        description:
          "Google Maps JavaScript API key for the browser map (plain string, HTTP-referrer restricted). Update after deployment.",
        secretStringValue: cdk.SecretValue.unsafePlainText("REPLACE_ME"),
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      },
    );

    // =========================================================================
    // IAM — Access role (App Runner pulls from ECR)
    // =========================================================================

    const accessRole = new iam.Role(this, "AppRunnerAccessRole", {
      roleName: `${props.appName}-ui-apprunner-access`,
      assumedBy: new iam.ServicePrincipal("build.apprunner.amazonaws.com"),
    });

    accessRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "ECRPullImage",
        effect: iam.Effect.ALLOW,
        actions: [
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchCheckLayerAvailability",
          "ecr:DescribeImages",
        ],
        resources: [props.uiEcrRepoArn],
      }),
    );

    accessRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "ECRAuth",
        effect: iam.Effect.ALLOW,
        actions: ["ecr:GetAuthorizationToken"],
        resources: ["*"],
      }),
    );

    // =========================================================================
    // IAM — Instance role (running container calls AgentCore)
    // =========================================================================

    const instanceRole = new iam.Role(this, "AppRunnerInstanceRole", {
      roleName: `${props.appName}-ui-apprunner-instance`,
      assumedBy: new iam.ServicePrincipal("tasks.apprunner.amazonaws.com"),
    });

    instanceRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "AgentCoreInvoke",
        effect: iam.Effect.ALLOW,
        actions: ["bedrock-agentcore:InvokeAgentRuntime"],
        resources: [
          `arn:aws:bedrock-agentcore:${region}:${accountId}:runtime/*`,
        ],
      }),
    );

    // App Runner resolves runtimeEnvironmentSecrets with the instance role
    instanceRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "ReadMapsBrowserKey",
        effect: iam.Effect.ALLOW,
        actions: ["secretsmanager:GetSecretValue"],
        resources: [mapsBrowserKeySecret.secretArn],
      }),
    );

    // =========================================================================
    // App Runner Service
    // =========================================================================

    const service = new apprunner.CfnService(this, "UiService", {
      serviceName: `${props.appName}-ui`,
      sourceConfiguration: {
        authenticationConfiguration: {
          accessRoleArn: accessRole.roleArn,
        },
        autoDeploymentsEnabled: true,
        imageRepository: {
          imageIdentifier: props.uiImageUri,
          imageRepositoryType: "ECR",
          imageConfiguration: {
            port: "8000",
            runtimeEnvironmentVariables: [
              { name: "AGENT_CONNECTION_MODE", value: "aws" },
              { name: "AGENT_RUNTIME_ARN", value: props.agentRuntimeArn },
              { name: "AWS_REGION", value: region },
              { name: "GOOGLE_MAPS_MAP_ID", value: props.mapsMapId },
            ],
            runtimeEnvironmentSecrets: [
              {
                name: "GOOGLE_MAPS_BROWSER_API_KEY",
                value: mapsBrowserKeySecret.secretArn,
              },
            ],
          },
        },
      },
      instanceConfiguration: {
        cpu: "1024",
        memory: "2048",
        instanceRoleArn: instanceRole.roleArn,
      },
      healthCheckConfiguration: {
        protocol: "TCP",
        interval: 10,
        timeout: 5,
        healthyThreshold: 1,
        unhealthyThreshold: 5,
      },
    });

    // Role policies must exist before App Runner resolves the secret
    service.node.addDependency(instanceRole);

    this.serviceUrl = service.attrServiceUrl;

    // =========================================================================
    // Stack Outputs
    // =========================================================================

    new cdk.CfnOutput(this, "UiServiceUrl", {
      value: `https://${service.attrServiceUrl}`,
      description: "Next.js UI public URL (App Runner)",
      exportName: `${props.appName}-UiServiceUrl`,
    });

    new cdk.CfnOutput(this, "UiServiceArn", {
      value: service.attrServiceArn,
      description: "App Runner Service ARN",
      exportName: `${props.appName}-UiServiceArn`,
    });
  }
}
