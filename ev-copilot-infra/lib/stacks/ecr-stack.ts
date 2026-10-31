import * as cdk from "aws-cdk-lib/core";
import { Construct } from "constructs";
import * as ecr from "aws-cdk-lib/aws-ecr";
import { BaseStackProps } from "../types";

export class EcrStack extends cdk.Stack {
  /** MCP server ECR repository */
  readonly repository: ecr.Repository;

  /** Agent ECR repository */
  readonly agentRepository: ecr.Repository;

  /** UI ECR repository */
  readonly uiRepository: ecr.Repository;

  constructor(scope: Construct, id: string, props: BaseStackProps) {
    super(scope, id, props);

    // MCP server ECR repository
    this.repository = new ecr.Repository(this, "EcrRepo", {
      repositoryName: `${props.appName.toLowerCase()}-mcp`,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      emptyOnDelete: false,
      lifecycleRules: [
        {
          description: "Keep last 10 images",
          maxImageCount: 10,
          rulePriority: 1,
          tagStatus: ecr.TagStatus.ANY,
        },
      ],
      imageScanOnPush: true,
    });

    // Agent ECR repository
    this.agentRepository = new ecr.Repository(this, "AgentEcrRepo", {
      repositoryName: `${props.appName.toLowerCase()}-agent`,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      emptyOnDelete: false,
      lifecycleRules: [
        {
          description: "Keep last 10 images",
          maxImageCount: 10,
          rulePriority: 1,
          tagStatus: ecr.TagStatus.ANY,
        },
      ],
      imageScanOnPush: true,
    });

    // UI ECR repository
    this.uiRepository = new ecr.Repository(this, "UiEcrRepo", {
      repositoryName: `${props.appName.toLowerCase()}-ui`,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      emptyOnDelete: false,
      lifecycleRules: [
        {
          description: "Keep last 10 images",
          maxImageCount: 10,
          rulePriority: 1,
          tagStatus: ecr.TagStatus.ANY,
        },
      ],
      imageScanOnPush: true,
    });

    // MCP ECR outputs
    new cdk.CfnOutput(this, "EcrRepositoryUri", {
      value: this.repository.repositoryUri,
      description: "MCP ECR Repository URI",
      exportName: `${props.appName}-EcrRepositoryUri`,
    });

    new cdk.CfnOutput(this, "EcrRepositoryName", {
      value: this.repository.repositoryName,
      description: "MCP ECR Repository Name",
      exportName: `${props.appName}-EcrRepositoryName`,
    });

    // Agent ECR outputs
    new cdk.CfnOutput(this, "AgentEcrRepositoryUri", {
      value: this.agentRepository.repositoryUri,
      description: "Agent ECR Repository URI",
      exportName: `${props.appName}-AgentEcrRepositoryUri`,
    });

    new cdk.CfnOutput(this, "AgentEcrRepositoryName", {
      value: this.agentRepository.repositoryName,
      description: "Agent ECR Repository Name",
      exportName: `${props.appName}-AgentEcrRepositoryName`,
    });

    // UI ECR outputs
    new cdk.CfnOutput(this, "UiEcrRepositoryUri", {
      value: this.uiRepository.repositoryUri,
      description: "UI ECR Repository URI",
      exportName: `${props.appName}-UiEcrRepositoryUri`,
    });

    new cdk.CfnOutput(this, "UiEcrRepositoryName", {
      value: this.uiRepository.repositoryName,
      description: "UI ECR Repository Name",
      exportName: `${props.appName}-UiEcrRepositoryName`,
    });
  }
}
